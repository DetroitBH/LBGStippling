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


# Allow the real difference seen on this MAP06R1BWT and immediately recalculate
# the displayed value after calibration.
rel = 'app/src/main/java/ca/crystalbunny/mideacomfort/AppPreferences.java'
s = read(rel)
old = '''    public void setSensorOffset(float value) {
        preferences.edit().putFloat(KEY_SENSOR_OFFSET, Math.max(-5.0f, Math.min(5.0f, value))).apply();
    }'''
new = '''    public void setSensorOffset(float value) {
        float clamped = Math.max(-15.0f, Math.min(15.0f, value));
        SharedPreferences.Editor editor = preferences.edit().putFloat(KEY_SENSOR_OFFSET, clamped);
        if (preferences.contains(KEY_TEMP_RAW)) {
            float raw = preferences.getFloat(KEY_TEMP_RAW, 0f);
            editor.putFloat(KEY_TEMP_CORRECTED, raw + clamped);
        }
        editor.apply();
    }'''
s = must_replace(s, old, new, 'sensor offset method')
write(rel, s)


# Replace the confusing two-field dialog with one clearly labelled field.
rel = 'app/src/main/java/ca/crystalbunny/mideacomfort/MainActivity.java'
s = read(rel)
start = s.index('    private void showCalibrationDialog() {')
end = s.index('    private void openBatterySettings() {', start)
method = '''    private void showCalibrationDialog() {
        int pad = Math.round(20 * getResources().getDisplayMetrics().density);
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setPadding(pad, 0, pad, 0);

        Float raw = prefs.getLastRawTemperature();
        Float corrected = prefs.getLastCorrectedTemperature();

        TextView rawInfo = new TextView(this);
        rawInfo.setTextSize(16);
        rawInfo.setText(raw == null
                ? "Локальное показание ещё не получено. Закрой окно, подожди 30 секунд и попробуй снова."
                : "Кондиционер сейчас передаёт: " + formatNumber(raw) + " °C");
        container.addView(rawInfo);

        TextView instruction = new TextView(this);
        instruction.setText("Ниже впиши ТОЛЬКО температуру, которую сейчас показывает SmartHome:");
        instruction.setTextSize(16);
        instruction.setPadding(0, pad / 2, 0, 0);
        container.addView(instruction);

        EditText smartHomeTemperature = new EditText(this);
        smartHomeTemperature.setHint("Например 24.0");
        smartHomeTemperature.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL | InputType.TYPE_NUMBER_FLAG_SIGNED);
        if (corrected != null) {
            smartHomeTemperature.setText(formatNumber(corrected));
            smartHomeTemperature.selectAll();
        }
        container.addView(smartHomeTemperature);

        TextView savedOffset = new TextView(this);
        savedOffset.setText("Сохранённая поправка: " + String.format(Locale.CANADA, "%+.1f °C", prefs.getSensorOffset()));
        savedOffset.setTextSize(15);
        savedOffset.setPadding(0, pad / 2, 0, 0);
        container.addView(savedOffset);

        TextView fixedRule = new TextView(this);
        fixedRule.setText("Автоматическое включение: только при 25.0 °C и выше");
        fixedRule.setTextSize(15);
        fixedRule.setPadding(0, pad / 2, 0, 0);
        container.addView(fixedRule);

        new MaterialAlertDialogBuilder(this)
                .setTitle("Синхронизация со SmartHome")
                .setMessage("Это не настройка температуры охлаждения. Здесь мы только выравниваем показание приложения со SmartHome.")
                .setView(container)
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Сохранить", (dialog, which) -> {
                    try {
                        Float latestRaw = prefs.getLastRawTemperature();
                        if (latestRaw == null) throw new NumberFormatException();
                        String text = smartHomeTemperature.getText().toString().trim().replace(',', '.');
                        float smartValue = Float.parseFloat(text);
                        if (smartValue < 10.0f || smartValue > 40.0f) throw new NumberFormatException();

                        float newOffset = smartValue - latestRaw;
                        prefs.setSensorOffset(newOffset);
                        prefs.setOnThreshold(25.0f);
                        render();
                        sendServiceAction(ThermostatService.ACTION_REFRESH);
                        Toast.makeText(this,
                                "Готово: " + formatNumber(smartValue) + " °C, поправка "
                                        + String.format(Locale.CANADA, "%+.1f °C", newOffset),
                                Toast.LENGTH_LONG).show();
                    } catch (NumberFormatException e) {
                        Toast.makeText(this, "Введи температуру из SmartHome, например 24.0", Toast.LENGTH_LONG).show();
                    }
                })
                .show();
    }

'''
s = s[:start] + method + s[end:]
write(rel, s)


# This is an in-place update of the FIX app, signed by the same key.
rel = 'app/build.gradle'
s = read(rel)
s = must_replace(s, 'versionCode 2', 'versionCode 3', 'version code')
s = must_replace(s, "versionName '2.0.1-fixed'", "versionName '2.0.2-fixed'", 'version name')
write(rel, s)
