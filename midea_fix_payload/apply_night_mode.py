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

# Persisted night-cycle state.
rel = 'app/src/main/java/ca/crystalbunny/mideacomfort/AppPreferences.java'
s = read(rel)
s = must_replace(s,
    '    private static final String KEY_ON_THRESHOLD = "on_threshold";\n',
    '    private static final String KEY_ON_THRESHOLD = "on_threshold";\n'
    '    private static final String KEY_NIGHT_ENABLED = "night_enabled";\n'
    '    private static final String KEY_NIGHT_PHASE_ON = "night_phase_on";\n'
    '    private static final String KEY_NIGHT_PHASE_END = "night_phase_end";\n'
    '    private static final String KEY_NIGHT_OFF_MINUTES = "night_off_minutes";\n',
    'night preference keys')
s = must_replace(s,
    '                .putBoolean(KEY_SERVICE, false)\n',
    '                .putBoolean(KEY_SERVICE, false)\n'
    '                .putBoolean(KEY_NIGHT_ENABLED, false)\n'
    '                .remove(KEY_NIGHT_PHASE_ON)\n'
    '                .remove(KEY_NIGHT_PHASE_END)\n',
    'clear night preferences')
anchor = '''    public boolean isAutoEnabled() {
'''
night_methods = '''    public boolean isNightEnabled() {
        return preferences.getBoolean(KEY_NIGHT_ENABLED, false);
    }

    public void setNightEnabled(boolean enabled) {
        preferences.edit().putBoolean(KEY_NIGHT_ENABLED, enabled).apply();
    }

    public boolean isNightOnPhase() {
        return preferences.getBoolean(KEY_NIGHT_PHASE_ON, true);
    }

    public long getNightPhaseEnd() {
        return preferences.getLong(KEY_NIGHT_PHASE_END, 0L);
    }

    public void setNightPhase(boolean onPhase, long endMillis) {
        preferences.edit()
                .putBoolean(KEY_NIGHT_PHASE_ON, onPhase)
                .putLong(KEY_NIGHT_PHASE_END, endMillis)
                .apply();
    }

    public void clearNightCycle() {
        preferences.edit().remove(KEY_NIGHT_PHASE_ON).remove(KEY_NIGHT_PHASE_END).apply();
    }

    public int getNightOffMinutes() {
        return preferences.getInt(KEY_NIGHT_OFF_MINUTES, 20);
    }

    public void setNightOffMinutes(int minutes) {
        preferences.edit().putInt(KEY_NIGHT_OFF_MINUTES, Math.max(10, Math.min(60, minutes))).apply();
    }

'''
s = must_replace(s, anchor, night_methods + anchor, 'night preference methods')
write(rel, s)

# Service: night mode ignores room-temperature control and uses a timed cycle.
rel = 'app/src/main/java/ca/crystalbunny/mideacomfort/ThermostatService.java'
s = read(rel)
s = must_replace(s,
    '    public static final String ACTION_REDISCOVER = "ca.crystalbunny.mideacomfort.REDISCOVER";\n',
    '    public static final String ACTION_REDISCOVER = "ca.crystalbunny.mideacomfort.REDISCOVER";\n'
    '    public static final String ACTION_NIGHT_START = "ca.crystalbunny.mideacomfort.NIGHT_START";\n'
    '    public static final String ACTION_NIGHT_STOP = "ca.crystalbunny.mideacomfort.NIGHT_STOP";\n',
    'night service actions')
s = must_replace(s,
    '    private static final long MANUAL_PAUSE_MS = 60 * 60_000L;\n',
    '    private static final long MANUAL_PAUSE_MS = 60 * 60_000L;\n'
    '    private static final long NIGHT_ON_MS = 10 * 60_000L;\n'
    '    private static final float NIGHT_TARGET = 20.0f;\n',
    'night service constants')
s = must_replace(s,
'''            case ACTION_RESUME_AUTO:
                prefs.setAutoEnabled(true);
                prefs.clearPause();
                runCycle();
                break;
''',
'''            case ACTION_RESUME_AUTO:
                prefs.setNightEnabled(false);
                prefs.clearNightCycle();
                prefs.setAutoEnabled(true);
                prefs.clearPause();
                runCycle();
                break;
            case ACTION_NIGHT_START:
                prefs.setAutoEnabled(false);
                prefs.clearPause();
                prefs.setNightEnabled(true);
                prefs.clearNightCycle();
                runCycle();
                break;
            case ACTION_NIGHT_STOP:
                stopNightAndPowerOff(config);
                break;
''',
    'night action handling')
# Both foreground refresh and normal polling must respect whichever control mode is active.
s = s.replace('state = applyThermostatIfNeeded(config, state);',
              'state = applyControlIfNeeded(config, state);')

start = s.index('    private void manualOn(DeviceConfig config) {')
end = s.index('    private void targetChanged(DeviceConfig config) {', start)
manual_block = '''    private void manualOn(DeviceConfig config) {
        prefs.setNightEnabled(false);
        prefs.clearNightCycle();
        prefs.setAutoEnabled(false);
        prefs.clearPause();
        try {
            AcState state = startCoolLowAndVerify(config, prefs.getTargetTemperature());
            prefs.setLastOnAt(System.currentTimeMillis());
            prefs.saveState(state, "Ручной режим · включён · COOL · LOW");
        } catch (Exception e) {
            prefs.saveError(cleanError(e));
        }
        publishState();
        scheduleCycle(POLL_ON_MS);
    }

    private void manualOff(DeviceConfig config) {
        prefs.setNightEnabled(false);
        prefs.clearNightCycle();
        prefs.setAutoEnabled(false);
        prefs.clearPause();
        try {
            AcState state = callWithRetry(() -> repository.powerOff(config));
            prefs.setLastOffAt(System.currentTimeMillis());
            prefs.saveState(state, "Ручной режим · выключен");
        } catch (Exception e) {
            prefs.saveError(cleanError(e));
        }
        publishState();
        scheduleCycle(POLL_OFF_MS);
    }

    private void stopNightAndPowerOff(DeviceConfig config) {
        prefs.setNightEnabled(false);
        prefs.clearNightCycle();
        prefs.setAutoEnabled(false);
        prefs.clearPause();
        try {
            AcState state = callWithRetry(() -> repository.powerOff(config));
            prefs.setLastOffAt(System.currentTimeMillis());
            prefs.saveState(state, "Остановлен до ручного включения");
        } catch (Exception e) {
            prefs.saveError(cleanError(e));
        }
        publishState();
        scheduleCycle(POLL_OFF_MS);
    }

'''
s = s[:start] + manual_block + s[end:]
s = must_replace(s,
'''            if (state.power) {
                state = callWithRetry(() -> repository.ensureLow(config, prefs.getTargetTemperature()));
            }
''',
'''            if (state.power) {
                float requested = prefs.isNightEnabled() ? NIGHT_TARGET : prefs.getTargetTemperature();
                state = callWithRetry(() -> repository.ensureLow(config, requested));
            }
''',
    'target change during night mode')
s = must_replace(s,
    '            scheduleCycle(state.power ? POLL_ON_MS : POLL_OFF_MS);\n',
    '            scheduleCycle(nextCycleDelay(state));\n',
    'mode-aware cycle scheduling')

start = s.index('    private AcState applyThermostatIfNeeded(DeviceConfig config, AcState state) throws Exception {')
end = s.index('    private AcState startCoolLowAndVerify', start)
old_thermostat = s[start:end]
control_methods = '''    private AcState applyControlIfNeeded(DeviceConfig config, AcState state) throws Exception {
        if (prefs.isNightEnabled()) return applyNightMode(config, state);
        return applyThermostatIfNeeded(config, state);
    }

    private AcState applyNightMode(DeviceConfig config, AcState state) throws Exception {
        long now = System.currentTimeMillis();
        long phaseEnd = prefs.getNightPhaseEnd();
        boolean onPhase = prefs.isNightOnPhase();

        if (phaseEnd == 0L) {
            onPhase = true;
            phaseEnd = now + NIGHT_ON_MS;
            prefs.setNightPhase(true, phaseEnd);
        } else if (now >= phaseEnd) {
            if (onPhase) {
                phaseEnd = now + prefs.getNightOffMinutes() * 60_000L;
                prefs.setNightPhase(false, phaseEnd);
                if (state.power) {
                    state = callWithRetry(() -> repository.powerOff(config));
                    prefs.setLastOffAt(now);
                }
                return state;
            }
            phaseEnd = now + NIGHT_ON_MS;
            prefs.setNightPhase(true, phaseEnd);
            state = startCoolLowAndVerify(config, NIGHT_TARGET);
            prefs.setLastOnAt(now);
            return state;
        }

        if (onPhase) {
            if (!state.power) {
                state = startCoolLowAndVerify(config, NIGHT_TARGET);
                prefs.setLastOnAt(now);
            } else {
                boolean wrongFan = state.fanSpeed == null || state.fanSpeed != 40;
                boolean wrongMode = state.mode == null || state.mode != 2;
                boolean wrongTarget = state.targetTemperature == null
                        || Math.abs(state.targetTemperature - NIGHT_TARGET) > 0.1;
                if (wrongFan || wrongMode || wrongTarget) {
                    state = callWithRetry(() -> repository.ensureLow(config, NIGHT_TARGET));
                }
            }
        } else if (state.power) {
            state = callWithRetry(() -> repository.powerOff(config));
            prefs.setLastOffAt(now);
        }
        return state;
    }

''' + old_thermostat + '''    private long nextCycleDelay(AcState state) {
        if (!prefs.isNightEnabled()) return state.power ? POLL_ON_MS : POLL_OFF_MS;
        long remaining = prefs.getNightPhaseEnd() - System.currentTimeMillis();
        if (remaining <= 0L) return 1_000L;
        long poll = prefs.isNightOnPhase() ? POLL_ON_MS : POLL_OFF_MS;
        return Math.max(1_000L, Math.min(poll, remaining));
    }

'''
s = s[:start] + control_methods + s[end:]

start = s.index('    private String statusFor(AcState state) {')
end = s.index('    private String pausedStatus', start)
old_status = s[start:end]
night_status = '''    private String statusFor(AcState state) {
        long now = System.currentTimeMillis();
        if (prefs.isNightEnabled()) {
            long seconds = Math.max(0L, (prefs.getNightPhaseEnd() - now + 999L) / 1000L);
            String left = String.format(Locale.CANADA, "%d:%02d", seconds / 60L, seconds % 60L);
            return prefs.isNightOnPhase()
                    ? "Ночь · COOL 20 °C · LOW · выключится через " + left
                    : "Ночь · пауза · включится через " + left;
        }
'''
# Reuse the existing method body after its opening and initial now declaration.
body = old_status.split('        long now = System.currentTimeMillis();\n', 1)[1]
night_status += body
s = s[:start] + night_status + s[end:]
s = must_replace(s,
    '        boolean shouldHold = prefs.isAutoEnabled() && prefs.isServiceEnabled();\n',
    '        boolean shouldHold = (prefs.isAutoEnabled() || prefs.isNightEnabled()) && prefs.isServiceEnabled();\n',
    'night wake/wifi locks')
write(rel, s)

# Activity UI and behavior.
rel = 'app/src/main/java/ca/crystalbunny/mideacomfort/MainActivity.java'
s = read(rel)
s = must_replace(s,
    '    private MaterialSwitch autoSwitch;\n',
    '    private MaterialSwitch autoSwitch;\n'
    '    private MaterialSwitch nightSwitch;\n'
    '    private TextView nightRuleText;\n'
    '    private MaterialButton nightIntervalButton;\n'
    '    private MaterialButton stopNightButton;\n'
    '    private MaterialButton minusButton;\n'
    '    private MaterialButton plusButton;\n',
    'night UI fields')
s = must_replace(s,
    '        autoSwitch = findViewById(R.id.autoSwitch);\n',
    '        autoSwitch = findViewById(R.id.autoSwitch);\n'
    '        nightSwitch = findViewById(R.id.nightSwitch);\n'
    '        nightRuleText = findViewById(R.id.nightRuleText);\n'
    '        nightIntervalButton = findViewById(R.id.nightIntervalButton);\n'
    '        stopNightButton = findViewById(R.id.stopNightButton);\n'
    '        minusButton = findViewById(R.id.minusButton);\n'
    '        plusButton = findViewById(R.id.plusButton);\n',
    'night view binding')
s = must_replace(s,
    '        findViewById(R.id.minusButton).setOnClickListener(v -> changeTarget(-0.5f));\n'
    '        findViewById(R.id.plusButton).setOnClickListener(v -> changeTarget(0.5f));\n',
    '        minusButton.setOnClickListener(v -> changeTarget(-0.5f));\n'
    '        plusButton.setOnClickListener(v -> changeTarget(0.5f));\n',
    'temperature button binding')
s = must_replace(s,
'''        autoSwitch.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (updatingUi) return;
            prefs.setAutoEnabled(isChecked);
            prefs.clearPause();
            prefs.setServiceEnabled(true);
            sendServiceAction(ThermostatService.ACTION_REFRESH);
            render();
        });
''',
'''        autoSwitch.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (updatingUi) return;
            if (isChecked) {
                prefs.setNightEnabled(false);
                prefs.clearNightCycle();
            }
            prefs.setAutoEnabled(isChecked);
            prefs.clearPause();
            prefs.setServiceEnabled(true);
            sendServiceAction(ThermostatService.ACTION_REFRESH);
            render();
        });

        nightSwitch.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (updatingUi) return;
            prefs.setServiceEnabled(true);
            sendServiceAction(isChecked
                    ? ThermostatService.ACTION_NIGHT_START
                    : ThermostatService.ACTION_NIGHT_STOP);
        });
        nightIntervalButton.setOnClickListener(v -> showNightIntervalDialog());
        stopNightButton.setOnClickListener(v -> sendServiceAction(ThermostatService.ACTION_NIGHT_STOP));
''',
    'night UI listeners')
insert_at = s.index('    private void openBatterySettings() {')
interval_method = '''    private void showNightIntervalDialog() {
        String[] labels = {"15 минут", "20 минут", "30 минут", "45 минут", "60 минут"};
        int[] values = {15, 20, 30, 45, 60};
        int selected = 1;
        int current = prefs.getNightOffMinutes();
        for (int i = 0; i < values.length; i++) if (values[i] == current) selected = i;
        final int initial = selected;
        new MaterialAlertDialogBuilder(this)
                .setTitle("Пауза между 10-минутными циклами")
                .setSingleChoiceItems(labels, initial, (dialog, which) -> {
                    prefs.setNightOffMinutes(values[which]);
                    dialog.dismiss();
                    render();
                    Toast.makeText(this, "Пауза: " + values[which] + " минут", Toast.LENGTH_SHORT).show();
                })
                .setNegativeButton("Отмена", null)
                .show();
    }

'''
s = s[:insert_at] + interval_method + s[insert_at:]
s = must_replace(s,
'''        updatingUi = true;
        autoSwitch.setChecked(prefs.isAutoEnabled());
        updatingUi = false;

        float target = prefs.getTargetTemperature();
''',
'''        updatingUi = true;
        autoSwitch.setChecked(prefs.isAutoEnabled());
        nightSwitch.setChecked(prefs.isNightEnabled());
        updatingUi = false;

        float target = prefs.getTargetTemperature();
''',
    'render night switch')
# Insert night details after daytime rule text has been set.
needle = '''                on, target));

        String error = prefs.getLastError();
'''
replacement = '''                on, target));
        nightRuleText.setText("10 минут COOL · 20 °C · LOW → "
                + prefs.getNightOffMinutes() + " минут выключен → повтор");
        nightIntervalButton.setText("Пауза между циклами: " + prefs.getNightOffMinutes() + " минут");
        boolean night = prefs.isNightEnabled();
        autoSwitch.setEnabled(!night);
        minusButton.setEnabled(!night);
        plusButton.setEnabled(!night);
        targetTemperature.setAlpha(night ? 0.45f : 1.0f);

        String error = prefs.getLastError();
'''
s = must_replace(s, needle, replacement, 'render night details')
write(rel, s)

# Add a dedicated night card.
rel = 'app/src/main/res/layout/activity_main.xml'
s = read(rel)
manual_marker = '''        <LinearLayout
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:layout_marginTop="14dp"
            android:background="@drawable/card_background"
            android:orientation="vertical">

            <TextView
                android:layout_width="wrap_content"
                android:layout_height="wrap_content"
                android:text="Ручное управление"'''
night_card = '''        <LinearLayout
            android:id="@+id/nightSection"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:layout_marginTop="14dp"
            android:background="@drawable/card_background"
            android:orientation="vertical">

            <TextView
                android:layout_width="wrap_content"
                android:layout_height="wrap_content"
                android:text="Ночной режим"
                android:textColor="@color/black"
                android:textSize="16sp"
                android:textStyle="bold" />

            <com.google.android.material.materialswitch.MaterialSwitch
                android:id="@+id/nightSwitch"
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:layout_marginTop="10dp"
                android:text="Циклическое охлаждение для сна"
                android:textColor="@color/black"
                android:textSize="16sp" />

            <TextView
                android:id="@+id/nightRuleText"
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:layout_marginTop="4dp"
                android:text="10 минут COOL · 20 °C · LOW → 20 минут выключен → повтор"
                android:textColor="@color/gray"
                android:textSize="13sp" />

            <com.google.android.material.button.MaterialButton
                android:id="@+id/nightIntervalButton"
                style="@style/Widget.Material3.Button.OutlinedButton"
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:layout_marginTop="10dp"
                android:text="Пауза между циклами: 20 минут" />

            <com.google.android.material.button.MaterialButton
                android:id="@+id/stopNightButton"
                style="@style/Widget.Material3.Button.OutlinedButton"
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:layout_marginTop="8dp"
                android:text="ОСТАНОВИТЬ И ВЫКЛЮЧИТЬ"
                android:textColor="@color/red"
                app:strokeColor="@color/red" />
        </LinearLayout>

''' + manual_marker
s = must_replace(s, manual_marker, night_card, 'night layout card')
s = s.replace('android:text="При включённой автоматике ручная команда ставит её на паузу на 1 час."',
              'android:text="Ручная команда отключает автоматический и ночной режимы."')
write(rel, s)

# Same package/signature means this installs as an update over FIX 2.0.2.
rel = 'app/build.gradle'
s = read(rel)
s = must_replace(s, 'versionCode 3', 'versionCode 4', 'night version code')
s = must_replace(s, "versionName '2.0.2-fixed'", "versionName '2.1.0-night'", 'night version name')
write(rel, s)
