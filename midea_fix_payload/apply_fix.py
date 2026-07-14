from pathlib import Path
import base64
import re

root = Path('/tmp/midea-build')

def read(rel):
    return (root / rel).read_text()

def write(rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)

def must_replace(text, old, new, label):
    if old not in text:
        raise RuntimeError(f'Patch target not found: {label}')
    return text.replace(old, new, 1)

# Use the complete fixed preferences implementation stored in the branch.
encoded = Path('midea_fix_payload/AppPreferences.java.b64').read_text().strip()
(root / 'app/src/main/java/ca/crystalbunny/mideacomfort/AppPreferences.java').write_bytes(base64.b64decode(encoded))

# Thermostat: start only at a fixed 25 C, require two readings, keep COOL + LOW.
rel = 'app/src/main/java/ca/crystalbunny/mideacomfort/ThermostatService.java'
s = read(rel)
s = must_replace(s,
    '    private WifiManager.WifiLock wifiLock;\n',
    '    private WifiManager.WifiLock wifiLock;\n'
    '    private int consecutiveHotReadings = 0;\n'
    '    private long lastHotReadingAt = 0L;\n',
    'thermostat fields')
s = must_replace(s,
    '        float onThreshold = target + prefs.getHysteresis();',
    '        float onThreshold = prefs.getOnThreshold();',
    'fixed on threshold')
old = '''        if (!state.power && correctedTemp >= onThreshold) {
            long lastOff = prefs.getLastOffAt();
            if (lastOff == 0L || now - lastOff >= MIN_OFF_MS) {
                AcState changed = startCoolLowAndVerify(config, target);
                prefs.setLastOnAt(now);
                return changed;
            }
        }
'''
new = '''        if (!state.power) {
            if (correctedTemp >= onThreshold) {
                // Safety: never start from one delayed/noisy value. Two fresh
                // readings at least 20 seconds apart must both be >= 25 C.
                if (lastHotReadingAt == 0L || now - lastHotReadingAt >= 20_000L) {
                    consecutiveHotReadings++;
                    lastHotReadingAt = now;
                }
                if (consecutiveHotReadings >= 2) {
                    long lastOff = prefs.getLastOffAt();
                    if (lastOff == 0L || now - lastOff >= MIN_OFF_MS) {
                        AcState changed = startCoolLowAndVerify(config, target);
                        prefs.setLastOnAt(now);
                        consecutiveHotReadings = 0;
                        lastHotReadingAt = 0L;
                        return changed;
                    }
                }
            } else {
                consecutiveHotReadings = 0;
                lastHotReadingAt = 0L;
            }
        } else {
            consecutiveHotReadings = 0;
            lastHotReadingAt = 0L;
        }
'''
s = must_replace(s, old, new, 'safe start block')
s = must_replace(s,
    '                "Авто · включится при %.1f °C", prefs.getTargetTemperature() + prefs.getHysteresis());',
    '                "Авто · включится только при %.1f °C", prefs.getOnThreshold());',
    'status threshold')
write(rel, s)

# UI: make the fixed start rule explicit and calibrate directly from SmartHome.
rel = 'app/src/main/java/ca/crystalbunny/mideacomfort/MainActivity.java'
s = read(rel)
start = s.index('    private void showCalibrationDialog() {')
end = s.index('    private void openBatterySettings() {', start)
method = '''    private void showCalibrationDialog() {
        int pad = Math.round(20 * getResources().getDisplayMetrics().density);
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setPadding(pad, 0, pad, 0);

        EditText smartHomeTemperature = new EditText(this);
        smartHomeTemperature.setHint("Температура сейчас в SmartHome, например 25.0");
        smartHomeTemperature.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL | InputType.TYPE_NUMBER_FLAG_SIGNED);
        container.addView(smartHomeTemperature);

        EditText offset = new EditText(this);
        offset.setHint("Или коррекция датчика, например -1.5");
        offset.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL | InputType.TYPE_NUMBER_FLAG_SIGNED);
        offset.setText(formatNumber(prefs.getSensorOffset()));
        container.addView(offset);

        TextView fixedRule = new TextView(this);
        fixedRule.setText("Автоматическое включение зафиксировано: только 25.0 °C и выше");
        fixedRule.setTextSize(16);
        fixedRule.setPadding(0, pad / 2, 0, 0);
        container.addView(fixedRule);

        new MaterialAlertDialogBuilder(this)
                .setTitle("Синхронизация со SmartHome")
                .setMessage("Впиши температуру, которую сейчас показывает SmartHome. Приложение рассчитает поправку для датчика у кондиционера.")
                .setView(container)
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Сохранить", (dialog, which) -> {
                    try {
                        String smartText = smartHomeTemperature.getText().toString().trim().replace(',', '.');
                        float newOffset;
                        Float raw = prefs.getLastRawTemperature();
                        if (!smartText.isEmpty()) {
                            if (raw == null) throw new NumberFormatException();
                            newOffset = Float.parseFloat(smartText) - raw;
                        } else {
                            newOffset = Float.parseFloat(offset.getText().toString().replace(',', '.'));
                        }
                        prefs.setSensorOffset(newOffset);
                        prefs.setOnThreshold(25.0f);
                        render();
                        sendServiceAction(ThermostatService.ACTION_REFRESH);
                        Toast.makeText(this, "Коррекция датчика: " + formatNumber(newOffset) + " °C", Toast.LENGTH_LONG).show();
                    } catch (NumberFormatException e) {
                        Toast.makeText(this, "Введи температуру, например 25.0", Toast.LENGTH_LONG).show();
                    }
                })
                .show();
    }

'''
s = s[:start] + method + s[end:]
s = must_replace(s,
    '        float on = target + prefs.getHysteresis();\n'
    '        autoRuleText.setText(String.format(Locale.CANADA,\n'
    '                "Включение при %.1f °C, выключение при %.1f °C. При включении всегда COOL + LOW.",\n'
    '                on, target));',
    '        float on = prefs.getOnThreshold();\n'
    '        autoRuleText.setText(String.format(Locale.CANADA,\n'
    '                "Включение всегда только при %.1f °C и выше. Выбранная температура %.1f °C — только для выключения. Всегда COOL + LOW.",\n'
    '                on, target));',
    'UI rule')
s = must_replace(s,
    '        mainHandler.post(periodicRender);\n    }',
    '        mainHandler.post(periodicRender);\n'
    '        if (prefs.getDeviceConfig() != null) {\n'
    '            sendServiceAction(ThermostatService.ACTION_REFRESH);\n'
    '        }\n'
    '    }',
    'refresh on start')
write(rel, s)

# Labels are honest about the sensor location and the fixed threshold.
rel = 'app/src/main/res/layout/activity_main.xml'
s = read(rel)
s = s.replace('android:text="Midea Comfort"', 'android:text="Midea Comfort FIX"', 1)
s = s.replace('android:text="ТЕМПЕРАТУРА В КОМНАТЕ"', 'android:text="ТЕМПЕРАТУРА ДЛЯ АВТОМАТИКИ"')
s = s.replace('android:text="Желаемая температура"', 'android:text="Охлаждать до"')
s = s.replace(
    'android:text="Включение при 25 °C, выключение при 24 °C. При включении всегда COOL + LOW."',
    'android:text="Включение всегда только при 25 °C и выше. Выбранная температура задаёт только выключение. Всегда COOL + LOW."')
write(rel, s)

# Install beside the old app and sign all future FIX builds with the same key.
rel = 'app/build.gradle'
s = read(rel)
s = s.replace("applicationId 'ca.crystalbunny.mideacomfort'", "applicationId 'ca.crystalbunny.mideacomfort.fix'")
s = s.replace("versionCode 1", "versionCode 2")
s = s.replace("versionName '1.0.0'", "versionName '2.0.1-fixed'")
s = s.replace("implementation 'androidx.core:core:1.19.0'", "implementation 'androidx.core:core:1.15.0'")
s = s.replace('    buildTypes {\n', '''    signingConfigs {
        personal {
            storeFile file('midea-comfort-fixed.jks')
            storePassword 'MideaComfort2026'
            keyAlias 'midea_fixed'
            keyPassword 'MideaComfort2026'
        }
    }

    buildTypes {
        debug { signingConfig signingConfigs.personal }
''')
s = s.replace('        release {\n', '        release {\n            signingConfig signingConfigs.personal\n')
write(rel, s)

rel = 'app/src/main/AndroidManifest.xml'
s = read(rel).replace('android:label="Midea Comfort"', 'android:label="Midea Comfort FIX"')
write(rel, s)

# Persistent signing key is stored as base64 text in the temporary branch.
encoded = Path('midea_fix_payload/midea-comfort-fixed.jks.b64').read_text().strip()
(root / 'app/midea-comfort-fixed.jks').write_bytes(base64.b64decode(encoded))
