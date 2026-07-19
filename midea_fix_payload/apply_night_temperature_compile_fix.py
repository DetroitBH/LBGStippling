from pathlib import Path

path = Path('/tmp/midea-build/app/src/main/java/ca/crystalbunny/mideacomfort/ThermostatService.java')
text = path.read_text()
old = '        float correctedTemp = state.indoorTemperature + prefs.getSensorOffset();\n'
new = '        float correctedTemp = state.indoorTemperature.floatValue() + prefs.getSensorOffset();\n'
if old not in text:
    raise RuntimeError('Night temperature conversion line not found')
path.write_text(text.replace(old, new, 1))
