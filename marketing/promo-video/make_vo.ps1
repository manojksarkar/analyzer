# Scratch voice-over with Windows text-to-speech, one WAV per scene, for timing the animatic only.
# Replace with a real voice-over before release.   powershell -File make_vo.ps1
Add-Type -AssemblyName System.Speech
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$out = Join-Path $here "out\vo"
New-Item -ItemType Directory -Force $out | Out-Null
$lines = Get-Content (Join-Path $here "vo.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$female = $voice.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Gender -eq "Female" } | Select-Object -First 1
if ($female) { $voice.SelectVoice($female.VoiceInfo.Name) }
$voice.Rate = 0
foreach ($p in $lines.PSObject.Properties) {
    $file = Join-Path $out ($p.Name + ".wav")
    $voice.SetOutputToWaveFile($file)
    $voice.Speak($p.Value)
}
$voice.Dispose()
Get-ChildItem $out | Select-Object Name, Length
