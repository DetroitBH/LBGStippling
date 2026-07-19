from pathlib import Path

root = Path('/tmp/midea-build')


def read(rel):
    return (root / rel).read_text()


def write(rel, text):
    (root / rel).write_text(text)


def must_replace(text, old, new, label):
    if old not in text:
        raise RuntimeError(f'Patch target not found: {label}')
    return text.replace(old, new, 1)


# Preferences: replace the old timed on/off cycle with a temperature-based
# night session which has a selectable 6-9 hour duration.
rel = 'app/src/main/java/ca/crystalbunny/mideacomfort/AppPreferences.java'
s = read(rel)
s = must_replace(
    s,
    '    private static final String KEY_NIGHT_OFF_MINUTES = "night_off_minutes";\n',
    '    private static final String KEY_NIGHT_OFF_MINUTES = "night_off_minutes"; // legacy\n'
    '    private static final String KEY_NIGHT_END_AT = "night_end_at";\n'
    '    private static final String KEY_NIGHT_START_TEMP = "night_start_temp";\n'
    '    private static final String KEY_NIGHT_COOLING_STARTED_AT = "night_cooling_started_at";\n'
    '    private static final String KEY_NIGHT_HOURS = "night_hours";\n',
    'night temperature keys')
s = must_replace(
    s,
    '                .remove(KEY_NIGHT_PHASE_END)\n',
    '                .remove(KEY_NIGHT_PHASE_END)\n'
    '                .remove(KEY_NIGHT_END_AT)\n'
    '                .remove(KEY_NIGHT_START_TEMP)\n'
    '                .remove(KEY_NIGHT_COOLING_STARTED_AT)\n',
    'clear new night state')

start = s.index('    public boolean isNightEnabled() {')
end = s.index('    public boolean isAutoEnabled() {', start)
night_preferences = '''    public boolean isNightEnabled() {
        return preferences.getBoolean(KEY_NIGHT_ENABLED, false);
    }

    public void setNightEnabled(boolean enabled) {
        preferences.edit().putBoolean(KEY_NIGHT_ENABLED, enabled).apply();
    }

    public int getNightHours() {
        return preferences.getInt(KEY_NIGHT_HOURS, 8);
    }

    public void setNightHours(int hours) {
        preferences.edit().putInt(KEY_NIGHT_HOURS, Math.max(6, Math.min(9, hours))).apply();
    }

    public long getNightEndAt() {
        return preferences.getLong(KEY_NIGHT_END_AT, 0L);
    }

    public void startNightSession(long now) {
        long duration = getNightHours() * 60L * 60_000L;
        preferences.edit()
                .putBoolean(KEY_NIGHT_ENABLED, true)
                .putLong(KEY_NIGHT_END_AT, now + duration)
                .remove(KEY_NIGHT_START_TEMP)
                .remove(KEY_NIGHT_COOLING_STARTED_AT)
                .remove(KEY_NIGHT_PHASE_ON)
                .remove(KEY_NIGHT_PHASE_END)
                .apply();
    }

    public Float getNightStartTemperature() {
        if (!preferences.contains(KEY_NIGHT_START_TEMP)) return null;
        return preferences.getFloat(KEY_NIGHT_START_TEMP, 0f);
    }

    public long getNightCoolingStartedAt() {
        return preferences.getLong(KEY_NIGHT_COOLING_STARTED_AT, 0L);
    }

    public void startNightCooling(float startTemperature, long now) {
        preferences.edit()
                .putFloat(KEY_NIGHT_START_TEMP, startTemperature)
                .putLong(KEY_NIGHT_COOLING_STARTED_AT, now)
                .apply();
    }

    public void clearNightCooling() {
        preferences.edit()
                .remove(KEY_NIGHT_START_TEMP)
                .remove(KEY_NIGHT_COOLING_STARTED_AT)
                .apply();
    }

    public void clearNightSession() {
        preferences.edit()
                .putBoolean(KEY_NIGHT_ENABLED, false)
                .remove(KEY_NIGHT_END_AT)
                .remove(KEY_NIGHT_START_TEMP)
                .remove(KEY_NIGHT_COOLING_STARTED_AT)
                .remove(KEY_NIGHT_PHASE_ON)
                .remove(KEY_NIGHT_PHASE_END)
                .apply();
    }

'''
s = s[:start] + night_preferences + s[end:]
write(rel, s)


# Service: start above 25 C, cool at 20 C / LOW until the calibrated room
# reading drops by 1 C, with a 20 minute fail-safe. There is no programmed
# rest interval: once off, it waits only for the temperature to rise above 25 C.
rel = 'app/src/main/java/ca/crystalbunny/mideacomfort/ThermostatService.java'
s = read(rel)
s = must_replace(
    s,
    '    private static final long NIGHT_ON_MS = 10 * 60_000L;\n'
    '    private static final float NIGHT_TARGET = 20.0f;\n',
    '    private static final long NIGHT_MAX_COOL_MS = 20 * 60_000L;\n'
    '    private static final long NIGHT_POLL_MS = 15_000L;\n'
    '    private static final float NIGHT_TARGET = 20.0f;\n'
    '    private static final float NIGHT_TRIGGER = 25.0f;\n'
    '    private static final float NIGHT_DROP = 1.0f;\n',
    'night temperature constants')

s = s.replace('prefs.clearNightCycle();', 'prefs.clearNightSession();')
s = must_replace(
    s,
    '''            case ACTION_NIGHT_START:
                prefs.setAutoEnabled(false);
                prefs.clearPause();
                prefs.setNightEnabled(true);
                prefs.clearNightSession();
                runCycle();
                break;
''',
    '''            case ACTION_NIGHT_START:
                prefs.setAutoEnabled(false);
                prefs.clearPause();
                prefs.startNightSession(System.currentTimeMillis());
                runCycle();
                break;
''',
    'start night session')

start = s.index('    private AcState applyNightMode(DeviceConfig config, AcState state) throws Exception {')
end = s.index('    private AcState applyThermostatIfNeeded(DeviceConfig config, AcState state) throws Exception {', start)
night_control = '''    private AcState applyNightMode(DeviceConfig config, AcState state) throws Exception {
        long now = System.currentTimeMillis();
        long nightEnd = prefs.getNightEndAt();

        // Smoothly migrate a running old night mode after an app update.
        if (nightEnd == 0L) {
            prefs.startNightSession(now);
            nightEnd = prefs.getNightEndAt();
        }

        if (now >= nightEnd) {
            prefs.clearNightSession();
            if (state.power) {
                state = callWithRetry(() -> repository.powerOff(config));
                prefs.setLastOffAt(now);
            }
            return state;
        }

        if (state.indoorTemperature == null) {
            throw new MideaException("Кондиционер не передал температуру в комнате.", "missing_temperature");
        }

        float correctedTemp = state.indoorTemperature + prefs.getSensorOffset();
        Float cycleStart = prefs.getNightStartTemperature();
        long coolingStartedAt = prefs.getNightCoolingStartedAt();

        if (!state.power) {
            // Any stale cycle marker is cleared as soon as the unit is confirmed off.
            if (cycleStart != null || coolingStartedAt != 0L) prefs.clearNightCooling();

            // Strictly above 25 C, as requested. At exactly 25.0 C it stays off.
            if (correctedTemp > NIGHT_TRIGGER) {
                prefs.startNightCooling(correctedTemp, now);
                state = startCoolLowAndVerify(config, NIGHT_TARGET);
                prefs.setLastOnAt(now);
            }
            return state;
        }

        // The night mode may be enabled while the AC is already running.
        if (cycleStart == null || coolingStartedAt == 0L) {
            if (correctedTemp <= NIGHT_TRIGGER) {
                state = callWithRetry(() -> repository.powerOff(config));
                prefs.setLastOffAt(now);
                prefs.clearNightCooling();
                return state;
            }
            cycleStart = correctedTemp;
            coolingStartedAt = now;
            prefs.startNightCooling(cycleStart, coolingStartedAt);
        }

        boolean droppedOneDegree = correctedTemp <= cycleStart - NIGHT_DROP;
        boolean reachedTimeLimit = now - coolingStartedAt >= NIGHT_MAX_COOL_MS;
        if (droppedOneDegree || reachedTimeLimit) {
            state = callWithRetry(() -> repository.powerOff(config));
            prefs.setLastOffAt(now);
            prefs.clearNightCooling();
            return state;
        }

        boolean wrongFan = state.fanSpeed == null || state.fanSpeed != 40;
        boolean wrongMode = state.mode == null || state.mode != 2;
        boolean wrongTarget = state.targetTemperature == null
                || Math.abs(state.targetTemperature - NIGHT_TARGET) > 0.1;
        if (wrongFan || wrongMode || wrongTarget) {
            state = callWithRetry(() -> repository.ensureLow(config, NIGHT_TARGET));
        }
        return state;
    }

'''
s = s[:start] + night_control + s[end:]

start = s.index('    private long nextCycleDelay(AcState state) {')
end = s.index('    private AcState startCoolLowAndVerify', start)
next_delay = '''    private long nextCycleDelay(AcState state) {
        if (prefs.isNightEnabled()) return NIGHT_POLL_MS;
        return state.power ? POLL_ON_MS : POLL_OFF_MS;
    }

'''
s = s[:start] + next_delay + s[end:]

old_night_status = '''        if (prefs.isNightEnabled()) {
            long seconds = Math.max(0L, (prefs.getNightPhaseEnd() - now + 999L) / 1000L);
            String left = String.format(Locale.CANADA, "%d:%02d", seconds / 60L, seconds % 60L);
            return prefs.isNightOnPhase()
                    ? "Ночь · COOL 20 °C · LOW · выключится через " + left
                    : "Ночь · пауза · включится через " + left;
        }
'''
new_night_status = '''        if (prefs.isNightEnabled()) {
            long minutes = Math.max(0L, (prefs.getNightEndAt() - now + 59_999L) / 60_000L);
            String sessionLeft = String.format(Locale.CANADA, "%d ч %02d мин", minutes / 60L, minutes % 60L);
            Float startTemp = prefs.getNightStartTemperature();
            if (state.power && startTemp != null) {
                float stopTemp = startTemp - NIGHT_DROP;
                long coolSeconds = Math.max(0L,
                        (NIGHT_MAX_COOL_MS - (now - prefs.getNightCoolingStartedAt()) + 999L) / 1000L);
                String coolLeft = String.format(Locale.CANADA, "%d:%02d", coolSeconds / 60L, coolSeconds % 60L);
                return String.format(Locale.CANADA,
                        "Ночь · охлаждает с %.1f до %.1f °C · COOL · LOW · максимум ещё %s",
                        startTemp, stopTemp, coolLeft);
            }
            return "Ночь · ждёт температуру выше 25.0 °C · режим ещё " + sessionLeft;
        }
'''
s = must_replace(s, old_night_status, new_night_status, 'temperature night status')
write(rel, s)


# Activity: use the existing night card, but replace pause controls with the
# sleep-duration selector and show the temperature rule clearly.
rel = 'app/src/main/java/ca/crystalbunny/mideacomfort/MainActivity.java'
s = read(rel)
s = s.replace('prefs.clearNightCycle();', 'prefs.clearNightSession();')
s = must_replace(
    s,
    '        nightIntervalButton.setOnClickListener(v -> showNightIntervalDialog());\n',
    '        nightIntervalButton.setOnClickListener(v -> showNightDurationDialog());\n',
    'night duration listener')

start = s.index('    private void showNightIntervalDialog() {')
end = s.index('    private void openBatterySettings() {', start)
duration_dialog = '''    private void showNightDurationDialog() {
        String[] labels = {"6 часов", "7 часов", "8 часов", "9 часов"};
        int[] values = {6, 7, 8, 9};
        int selected = 2;
        int current = prefs.getNightHours();
        for (int i = 0; i < values.length; i++) if (values[i] == current) selected = i;
        final int initial = selected;
        new MaterialAlertDialogBuilder(this)
                .setTitle("Сколько часов должен работать ночной режим")
                .setSingleChoiceItems(labels, initial, (dialog, which) -> {
                    prefs.setNightHours(values[which]);
                    dialog.dismiss();
                    render();
                    Toast.makeText(this, "Ночной режим: " + values[which] + " часов", Toast.LENGTH_SHORT).show();
                })
                .setNegativeButton("Отмена", null)
                .show();
    }

'''
s = s[:start] + duration_dialog + s[end:]

old_render = '''        nightRuleText.setText("10 минут COOL · 20 °C · LOW → "
                + prefs.getNightOffMinutes() + " минут выключен → повтор");
        nightIntervalButton.setText("Пауза между циклами: " + prefs.getNightOffMinutes() + " минут");
        boolean night = prefs.isNightEnabled();
        autoSwitch.setEnabled(!night);
        minusButton.setEnabled(!night);
        plusButton.setEnabled(!night);
        targetTemperature.setAlpha(night ? 0.45f : 1.0f);
'''
new_render = '''        nightRuleText.setText("Если температура выше 25 °C: COOL · 20 °C · LOW. "
                + "Выключение после снижения на 1 °C или максимум через 20 минут.");
        nightIntervalButton.setText("Длительность ночного режима: " + prefs.getNightHours() + " часов");
        boolean night = prefs.isNightEnabled();
        autoSwitch.setEnabled(!night);
        nightIntervalButton.setEnabled(!night);
        minusButton.setEnabled(!night);
        plusButton.setEnabled(!night);
        targetTemperature.setAlpha(night ? 0.45f : 1.0f);
'''
s = must_replace(s, old_render, new_render, 'temperature night UI')
write(rel, s)


# Layout wording: no timed cycles and no dry mode.
rel = 'app/src/main/res/layout/activity_main.xml'
s = read(rel)
s = s.replace('android:text="Циклическое охлаждение для сна"',
              'android:text="Ночной режим по температуре"')
s = s.replace('android:text="10 минут COOL · 20 °C · LOW → 20 минут выключен → повтор"',
              'android:text="Выше 25 °C: COOL · 20 °C · LOW. Выключение после снижения на 1 °C или через 20 минут."')
s = s.replace('android:text="Пауза между циклами: 20 минут"',
              'android:text="Длительность ночного режима: 8 часов"')
write(rel, s)


# Installs directly over FIX 2.0.2 and the uninstalled experimental 2.1 build.
rel = 'app/build.gradle'
s = read(rel)
s = must_replace(s, 'versionCode 4', 'versionCode 5', 'temperature night version code')
s = must_replace(s, "versionName '2.1.0-night'", "versionName '2.2.0-night-temperature'", 'temperature night version name')
write(rel, s)
