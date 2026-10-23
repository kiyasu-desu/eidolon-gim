$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
try {
    Add-Type -AssemblyName System.Speech
    if ($request.action -eq 'check') {
        $synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
        try {
            $voices = @($synth.GetInstalledVoices() | Where-Object Enabled | ForEach-Object {
                @{ name = $_.VoiceInfo.Name; language = $_.VoiceInfo.Culture.Name }
            })
            $recognizers = @([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | ForEach-Object {
                @{ name = $_.Name; language = $_.Culture.Name }
            })
            @{ voices = $voices; recognizers = $recognizers } | ConvertTo-Json -Depth 5 -Compress
        } finally { $synth.Dispose() }
    } elseif ($request.action -eq 'tts') {
        $synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
        try {
            $synth.SelectVoice($request.voice)
            $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
                [int]$request.sample_rate,
                [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
                [System.Speech.AudioFormat.AudioChannel]::Mono)
            $synth.SetOutputToWaveFile($request.path, $format)
            $synth.Speak($request.text)
            $synth.SetOutputToNull()
            '{}'  # Audio is read only after the process has closed its file.
        } finally { $synth.Dispose() }
    } elseif ($request.action -eq 'stt') {
        $engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new(
            [System.Globalization.CultureInfo]::GetCultureInfo($request.language))
        try {
            $engine.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
            $engine.SetInputToWaveFile($request.path)
            $segments = @()
            # Bounded even if a broken recognizer keeps returning results at EOF.
            for ($index = 0; $index -lt 120; $index++) {
                try { $result = $engine.Recognize([TimeSpan]::FromSeconds(20)) }
                catch {
                    # System.Speech can throw at file EOF after returning its final result.
                    if ($segments.Count -gt 0 -and $_.Exception.InnerException -is [System.InvalidOperationException]) { break }
                    throw
                }
                if ($null -eq $result) { break }
                if ($result.Text) { $segments += $result.Text }
            }
            @{ text = ($segments -join ' ') } | ConvertTo-Json -Compress
        } finally { $engine.Dispose() }
    } else { throw 'Unknown speech action' }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
