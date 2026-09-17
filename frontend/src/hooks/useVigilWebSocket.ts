import { useState, useEffect, useRef, useCallback } from 'react';
import type { SecurityTelemetry } from '../types';

export function useVigilWebSocket() {
  const [telemetry, setTelemetry] = useState<SecurityTelemetry>({
    session_id: undefined,
    policy_version: '2026.09.1-production',
    connection_status: 'DISCONNECTED',
    call_status: 'MONITORING',
    voice_authenticity: 91,
    speaker_match: 86,
    liveness: 52,
    deepfake_probability: 93,
    risk_score: 91,
    risk_level: 'CRITICAL',
    action: 'BLOCK',
    confidence: 0.94,
    latency_ms: 18,
    model_version: 'WavLM+AASIST+ECAPA',
    vad_active: true,
    sample_rate: 16000,
    chunk_duration: '2.0s',
    threat_signals: [
      'Synthetic speech indicators',
      'Low liveness',
      'Identity uncertainty',
      'Financial request',
    ],
    timeline: [
      { id: '1', time: '00:02', verdict: 'Genuine', confidence: 0.95, detail: 'Nominal acoustic match' },
      { id: '2', time: '00:04', verdict: 'Genuine', confidence: 0.92, detail: 'Valid prosodic rhythm' },
      { id: '3', time: '00:06', verdict: 'Suspicious', confidence: 0.68, detail: 'Loudspeaker replay hint' },
      { id: '4', time: '00:08', verdict: 'Synthetic', confidence: 0.88, detail: 'WavLM vocoder artifact spike' },
      { id: '5', time: '00:10', verdict: 'Critical', confidence: 0.94, detail: 'Urgent OTP financial request' },
    ],
    conversation: {
      intent: 'FINANCIAL_REQUEST',
      risk_signal: 0.88,
      evidence: 'Please send me the OTP password immediately',
    },
    active_challenge: null,
  });

  const [isStreaming, setIsStreaming] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const lastPingTimeRef = useRef<number>(0);
  const recognitionRef = useRef<any>(null);

  // Connect to FastAPI WebSocket Stream
  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    // Default fallback to 8000 if running under Vite standalone dev port
    const wsTarget = host.includes(':5173')
      ? `${protocol}//127.0.0.1:8000/api/v1/stream/ingest`
      : `${protocol}//${host}/api/v1/stream/ingest`;

    setTelemetry((prev) => ({ ...prev, connection_status: 'CONNECTING' }));

    try {
      const ws = new WebSocket(wsTarget);
      wsRef.current = ws;

      ws.onopen = () => {
        setTelemetry((prev) => ({ ...prev, connection_status: 'CONNECTED' }));
        lastPingTimeRef.current = performance.now();
      };

      ws.onmessage = (event) => {
        const roundtrip = Math.round(performance.now() - lastPingTimeRef.current);
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'TELEMETRY' && msg.data) {
            const d = msg.data;
            setTelemetry((prev) => {
              const deepfakeProb = Math.round((d.deepfake?.deepfake_score || d.deepfake?.spoof_probability || 0.1) * 100);
              const authenticity = Math.max(0, 100 - deepfakeProb);
              const speakerScore = Math.round((d.speaker?.similarity || 0.85) * 100);
              const livenessScore = Math.round((d.liveness?.liveness_score || 0.75) * 100);
              const risk = d.risk || {};

              return {
                ...prev,
                latency_ms: roundtrip > 0 && roundtrip < 500 ? roundtrip : prev.latency_ms,
                voice_authenticity: authenticity,
                speaker_match: speakerScore,
                liveness: livenessScore,
                deepfake_probability: deepfakeProb,
                risk_score: risk.risk_score !== undefined ? risk.risk_score : prev.risk_score,
                risk_level: risk.risk_level || prev.risk_level,
                action: risk.action || risk.recommended_action || prev.action,
                confidence: risk.confidence !== undefined ? risk.confidence : prev.confidence,
                policy_version: risk.policy_version || prev.policy_version,
                vad_active: !!d.vad?.speech_detected,
              };
            });
          } else if (msg.type === 'TRANSCRIPT_STORED') {
            setTelemetry((prev) => ({
              ...prev,
              live_transcript: msg.text,
              conversation: {
                intent: msg.intent || prev.conversation?.intent || 'ANALYZED',
                risk_signal: msg.risk_score !== undefined ? msg.risk_score / 100 : prev.conversation?.risk_signal || 0.1,
                evidence: msg.evidence || `Transcribed: "${msg.text}"`,
                transcript: msg.text,
              },
              risk_score: msg.risk_score !== undefined ? msg.risk_score : prev.risk_score,
              risk_level: msg.risk_level || prev.risk_level,
              action: msg.action || prev.action,
            }));
          }
        } catch {
          // Non-JSON or binary
        }
      };

      ws.onclose = () => {
        setTelemetry((prev) => ({ ...prev, connection_status: 'DISCONNECTED' }));
        setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      setTelemetry((prev) => ({ ...prev, connection_status: 'DISCONNECTED' }));
      setTimeout(connect, 3000);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  // Start / Stop Microphone Stream
  const toggleStreaming = async () => {
    if (isStreaming) {
      // Stop
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop();
        } catch {
          // ignore
        }
        recognitionRef.current = null;
      }
      mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
      processorRef.current?.disconnect();
      audioContextRef.current?.close();
      setIsStreaming(false);
      setTelemetry((prev) => ({ ...prev, vad_active: false }));
    } else {
      // Start
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaStreamRef.current = stream;

        const audioCtx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)({
          sampleRate: 16000,
        });
        audioContextRef.current = audioCtx;

        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        analyserRef.current = analyser;

        // Streaming PCM processor
        const processor = audioCtx.createScriptProcessor(4096, 1, 1);
        source.connect(processor);
        processor.connect(audioCtx.destination);
        processorRef.current = processor;

        processor.onaudioprocess = (e) => {
          const input = e.inputBuffer.getChannelData(0);
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            // Convert float32 to int16 PCM
            const pcmBuffer = new Int16Array(input.length);
            for (let i = 0; i < input.length; i++) {
              const s = Math.max(-1, Math.min(1, input[i]));
              pcmBuffer[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
            }
            lastPingTimeRef.current = performance.now();
            wsRef.current.send(pcmBuffer.buffer);
          }
        };

        // Real-time Speech-to-Text Transcription via Web Speech API
        const SpeechRec = (window as unknown as { SpeechRecognition?: any; webkitSpeechRecognition?: any }).SpeechRecognition ||
          (window as unknown as { SpeechRecognition?: any; webkitSpeechRecognition?: any }).webkitSpeechRecognition;

        if (SpeechRec) {
          try {
            const recognition = new SpeechRec();
            recognition.continuous = true;
            recognition.interimResults = true;
            recognition.lang = 'en-US';

            recognition.onresult = (evt: any) => {
              let interim = '';
              let finalTxt = '';
              for (let i = evt.resultIndex; i < evt.results.length; ++i) {
                const item = evt.results[i][0].transcript;
                if (evt.results[i].isFinal) {
                  finalTxt += item + ' ';
                } else {
                  interim += item;
                }
              }

              const currentPhrase = (finalTxt || interim).trim();
              if (currentPhrase) {
                setTelemetry((prev) => ({
                  ...prev,
                  live_transcript: currentPhrase,
                  conversation: {
                    intent: prev.conversation?.intent || 'NOMINAL',
                    risk_signal: prev.conversation?.risk_signal || 0.05,
                    evidence: `Transcribed caller speech: "${currentPhrase}"`,
                    transcript: currentPhrase,
                  },
                }));
              }

              if (finalTxt.trim() && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({
                  type: 'TRANSCRIPT',
                  text: finalTxt.trim(),
                  is_final: true,
                  caller_id: 'MIC_CALLER',
                }));
              }
            };

            recognition.onend = () => {
              // Automatically restart recognition while microphone stream is alive
              if (mediaStreamRef.current && mediaStreamRef.current.active) {
                try {
                  recognition.start();
                } catch {
                  // ignore
                }
              }
            };

            recognition.start();
            recognitionRef.current = recognition;
          } catch (sttErr) {
            console.warn('Speech recognition init notice:', sttErr);
          }
        }

        setIsStreaming(true);
      } catch (err) {
        console.warn('Microphone access unavailable or denied:', err);
      }
    }
  };

  // Simulator for Demo Scenarios
  const simulateScenario = (scenario: 'GENUINE' | 'CLONED' | 'REPLAY' | 'SCAM') => {
    switch (scenario) {
      case 'GENUINE':
        setTelemetry((prev) => ({
          ...prev,
          call_status: 'MONITORING',
          voice_authenticity: 96,
          speaker_match: 94,
          liveness: 91,
          deepfake_probability: 4,
          risk_score: 8,
          risk_level: 'LOW',
          action: 'ALLOW',
          confidence: 0.95,
          threat_signals: [],
          conversation: {
            intent: 'BENIGN_CONVERSATION',
            risk_signal: 0.05,
            evidence: 'Hey Aniket, are we still meeting for lunch today?',
          },
          timeline: [
            ...prev.timeline.slice(-4),
            { id: String(Date.now()), time: 'NOW', verdict: 'Genuine', confidence: 0.96, detail: 'Clean acoustic match' },
          ],
        }));
        break;

      case 'CLONED':
        setTelemetry((prev) => ({
          ...prev,
          call_status: 'BLOCKED',
          voice_authenticity: 8,
          speaker_match: 88,
          liveness: 42,
          deepfake_probability: 96,
          risk_score: 94,
          risk_level: 'CRITICAL',
          action: 'BLOCK',
          confidence: 0.96,
          threat_signals: [
            'Synthetic speech indicators',
            'Neural vocoder high-band phase glitch',
            'Targeted voice clone detected',
          ],
          conversation: null,
          timeline: [
            ...prev.timeline.slice(-4),
            { id: String(Date.now()), time: 'NOW', verdict: 'Critical', confidence: 0.96, detail: 'AI voice clone detected' },
          ],
        }));
        break;

      case 'REPLAY':
        setTelemetry((prev) => ({
          ...prev,
          call_status: 'WARNED',
          voice_authenticity: 35,
          speaker_match: 78,
          liveness: 18,
          deepfake_probability: 65,
          risk_score: 74,
          risk_level: 'HIGH',
          action: 'WARN',
          confidence: 0.89,
          threat_signals: [
            'Low liveness',
            'Loudspeaker frequency resonance peak',
            'Pre-recorded replay attack probable',
          ],
          timeline: [
            ...prev.timeline.slice(-4),
            { id: String(Date.now()), time: 'NOW', verdict: 'Suspicious', confidence: 0.89, detail: 'Loudspeaker replay detected' },
          ],
        }));
        break;

      case 'SCAM':
        setTelemetry((prev) => ({
          ...prev,
          call_status: 'CHALLENGING',
          voice_authenticity: 12,
          speaker_match: 84,
          liveness: 38,
          deepfake_probability: 92,
          risk_score: 95,
          risk_level: 'CRITICAL',
          action: 'BLOCK',
          confidence: 0.98,
          threat_signals: [
            'Synthetic speech indicators',
            'Low liveness',
            'Identity uncertainty',
            'Financial request',
            'Urgent OTP / UPI transfer solicitation',
          ],
          conversation: {
            intent: 'FINANCIAL_REQUEST',
            risk_signal: 0.95,
            evidence: 'This is bank security. Read the 6-digit OTP code sent to your phone right now.',
          },
          timeline: [
            ...prev.timeline.slice(-4),
            { id: String(Date.now()), time: 'NOW', verdict: 'Critical', confidence: 0.98, detail: 'Voice clone + Financial scam' },
          ],
        }));
        break;
    }
  };

  // Operator Actions
  const triggerVerifyIdentity = () => {
    setTelemetry((prev) => ({
      ...prev,
      timeline: [
        ...prev.timeline.slice(-4),
        { id: String(Date.now()), time: 'NOW', verdict: 'Suspicious', confidence: 0.85, detail: 'Operator triggered Biometric Re-verification' },
      ],
    }));
  };

  const triggerChallenge = () => {
    const prompts = [
      'Please repeat: blue mango.',
      'Please say: 7429.',
      'Please say: purple horizon.',
      'Please repeat: rapid river 81.',
    ];
    const chosenPrompt = prompts[Math.floor(Math.random() * prompts.length)];

    setTelemetry((prev) => ({
      ...prev,
      call_status: 'CHALLENGING',
      action: 'CHALLENGE',
      active_challenge: {
        challenge_id: 'ch_' + Math.random().toString(36).substring(7),
        prompt: chosenPrompt,
        expires_in_sec: 15,
        status: 'PENDING',
      },
      timeline: [
        ...prev.timeline.slice(-4),
        { id: String(Date.now()), time: 'NOW', verdict: 'Suspicious', confidence: 0.90, detail: `Dispatched Challenge: "${chosenPrompt}"` },
      ],
    }));
  };

  const triggerWarn = () => {
    setTelemetry((prev) => ({
      ...prev,
      call_status: 'WARNED',
      action: 'WARN',
      timeline: [
        ...prev.timeline.slice(-4),
        { id: String(Date.now()), time: 'NOW', verdict: 'Suspicious', confidence: 0.88, detail: 'Operator issued security warning alert to user' },
      ],
    }));
  };

  const triggerBlock = () => {
    setTelemetry((prev) => ({
      ...prev,
      call_status: 'BLOCKED',
      action: 'BLOCK',
      risk_score: 99,
      risk_level: 'CRITICAL',
      timeline: [
        ...prev.timeline.slice(-4),
        { id: String(Date.now()), time: 'NOW', verdict: 'Critical', confidence: 0.99, detail: 'Operator executed emergency call BLOCK & disconnect' },
      ],
    }));
  };

  return {
    telemetry,
    isStreaming,
    toggleStreaming,
    audioAnalyser: analyserRef.current,
    simulateScenario,
    triggerVerifyIdentity,
    triggerChallenge,
    triggerWarn,
    triggerBlock,
  };
}
