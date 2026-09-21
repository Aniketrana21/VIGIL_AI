import { useState, useEffect, useRef, useCallback } from 'react';
import type { SecurityTelemetry } from '../types';
import { getUserSession } from '../lib/session';

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
  const dashboardWsRef = useRef<WebSocket | null>(null);
  const [latestIncomingCall, setLatestIncomingCall] = useState<any | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const lastPingTimeRef = useRef<number>(0);
  const recognitionRef = useRef<any>(null);
  const pendingSpeechTimeoutRef = useRef<any>(null);
  const lastTransmittedPhraseRef = useRef<string>('');

  // Cleanly stops microphone audio capture
  const stopAudioStreaming = useCallback(() => {
    if (pendingSpeechTimeoutRef.current) {
      clearTimeout(pendingSpeechTimeoutRef.current);
    }
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {}
      recognitionRef.current = null;
    }
    mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
    mediaStreamRef.current = null;
    processorRef.current?.disconnect();
    processorRef.current = null;
    audioContextRef.current?.close();
    audioContextRef.current = null;
    setIsStreaming(false);
    setTelemetry((prev) => ({ ...prev, vad_active: false }));
  }, []);

  // Connect to Laptop SOC Dashboard WebSocket Event Bus (/ws/dashboard)
  const connectDashboardWs = useCallback(() => {
    const session = getUserSession();
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const baseTarget = host.includes(':5173')
      ? `${protocol}//127.0.0.1:8000/ws/dashboard`
      : `${protocol}//${host}/ws/dashboard`;
    const wsTarget = `${baseTarget}?user_id=${encodeURIComponent(session.userId)}`;

    try {
      const dws = new WebSocket(wsTarget);
      dashboardWsRef.current = dws;

      dws.onopen = () => {
        console.log('⚡ Connected to VIGIL-AI Dashboard WebSocket Event Bus:', wsTarget);
      };

      dws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.event === 'incoming_call') {
            console.log('🚨 Incoming Call Event received via WebSocket:', data);
            setLatestIncomingCall(data);
            setTelemetry((prev) => ({
              ...prev,
              active_call: {
                call_id: data.call_id,
                phone_number: data.phone_number,
                normalized_phone_number: data.normalized_phone_number,
                masked_phone: data.masked_phone,
                caller_name: data.caller_name,
                company: data.company,
                company_verification_status: data.company_verification_status,
                contact_known: data.contact_known,
                caller_type: data.caller_type,
                previous_calls: data.previous_calls || 0,
                calls_today: data.calls_today || 0,
                last_call_timestamp: data.last_call_timestamp,
                initial_risk: data.initial_risk || 0,
                risk_level: data.risk_level || 'LOW',
                recommended_action: data.recommended_action || 'ALLOW',
                speaker_verification_status: data.speaker_verification_status || 'WAITING',
                deepfake_detection_status: data.deepfake_detection_status || 'WAITING',
                liveness_status: data.liveness_status || 'WAITING',
                cellular_audio_available: data.cellular_audio_available ?? false,
                call_transport: data.call_transport || 'CELLULAR',
                timestamp: data.timestamp,
                threat_signals: data.threat_signals || [],
              },
              risk_score: data.initial_risk !== undefined ? data.initial_risk : prev.risk_score,
              risk_level: (data.risk_level as any) || prev.risk_level,
              action: (data.recommended_action as any) || prev.action,
              call_status: 'RINGING',
              threat_signals: data.threat_signals || prev.threat_signals,
            }));
          } else if (data.event === 'analysis_update') {
            setTelemetry((prev) => {
              const deepfakeProb = data.voice_deepfake_pct !== undefined ? data.voice_deepfake_pct : Math.round((data.deepfake_probability || 0) * 100);
              const speakerScore = data.voice_identity_pct !== undefined ? data.voice_identity_pct : (data.speaker_similarity !== null && data.speaker_similarity !== undefined ? Math.round(data.speaker_similarity * 100) : prev.speaker_match);
              const livenessScore = data.voice_liveness_pct !== undefined ? data.voice_liveness_pct : Math.round((data.liveness_score || 0.8) * 100);
              const authenticity = Math.max(0, 100 - deepfakeProb);

              return {
                ...prev,
                deepfake_probability: deepfakeProb,
                voice_authenticity: authenticity,
                speaker_match: speakerScore,
                liveness: livenessScore,
                risk_score: data.risk_score !== undefined ? data.risk_score : prev.risk_score,
                risk_level: (data.risk_level as any) || prev.risk_level,
                action: (data.action as any) || prev.action,
                vad_active: data.voice_activity === 'YES',
                live_transcript: data.transcript_segment || prev.live_transcript,
                active_call: prev.active_call ? {
                  ...prev.active_call,
                  speaker_verification_status: speakerScore >= 85 ? 'VERIFIED' : (speakerScore < 40 ? 'MISMATCH' : 'ANALYZING'),
                  deepfake_detection_status: deepfakeProb >= 70 ? 'SYNTHETIC' : 'CLEAN',
                  liveness_status: livenessScore >= 50 ? 'LIVE' : 'REPLAY',
                  voice_activity: data.voice_activity,
                } : null,
              };
            });
          } else if (data.event === 'risk_update') {
            setTelemetry((prev) => ({
              ...prev,
              risk_score: data.risk_score,
              risk_level: (data.risk_level as any) || prev.risk_level,
              action: (data.action as any) || prev.action,
              threat_signals: data.signals || prev.threat_signals,
            }));
          } else if (data.event === 'call_terminated') {
            console.warn('🛑 AUTOMATIC CALL TERMINATION EVENT RECEIVED VIA WEBSOCKET:', data);
            stopAudioStreaming();
            setTelemetry((prev) => ({
              ...prev,
              call_status: 'TERMINATED',
              action: 'TERMINATE',
              risk_level: 'CRITICAL',
              risk_score: data.risk_score || 100,
              explanation: `🛑 CALL AUTOMATICALLY TERMINATED: ${data.reason || 'High-confidence synthetic voice attack detected.'}`,
              threat_signals: [
                'AUTOMATIC ENFORCEMENT: CALL TERMINATED',
                ...(data.signals || ['High synthetic probability', 'Speaker mismatch']),
              ],
            }));
          }
        } catch (e) {
          // ignore
        }
      };

      dws.onclose = () => {
        setTimeout(connectDashboardWs, 2500);
      };
    } catch {
      setTimeout(connectDashboardWs, 3000);
    }
  }, [stopAudioStreaming]);

  // Connect to FastAPI Audio Ingest Stream (/api/v1/stream/ingest)
  const connect = useCallback(() => {
    const session = getUserSession();
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const baseTarget = host.includes(':5173')
      ? `${protocol}//127.0.0.1:8000/api/v1/stream/ingest`
      : `${protocol}//${host}/api/v1/stream/ingest`;
    const wsTarget = `${baseTarget}?user_id=${encodeURIComponent(session.userId)}&device_id=${encodeURIComponent(session.deviceUuid)}`;

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

          // Check for call termination signal from audio streamer
          if (msg.type === 'CALL_TERMINATED' || msg.action === 'TERMINATE' || msg.event === 'call_terminated') {
            console.warn('🛑 Ingest stream received CALL_TERMINATED! Automatically cutting audio.');
            stopAudioStreaming();
            setTelemetry((prev) => ({
              ...prev,
              call_status: 'TERMINATED',
              action: 'TERMINATE',
              risk_level: 'CRITICAL',
              risk_score: msg.risk_score || 100,
              explanation: `🛑 CALL TERMINATED: ${msg.reason || 'High-confidence synthetic voice attack detected.'}`,
              threat_signals: [
                'AUTOMATIC ENFORCEMENT: CALL TERMINATED',
                'High synthetic probability',
                'Speaker mismatch'
              ]
            }));
            return;
          }

          if (msg.type === 'TELEMETRY' && msg.data) {
            const d = msg.data;
            setTelemetry((prev) => {
              const deepfakeProb = Math.round((d.deepfake?.deepfake_score || d.deepfake?.spoof_probability || 0.1) * 100);
              const authenticity = Math.max(0, 100 - deepfakeProb);
              const speakerScore = Math.round((d.speaker?.similarity || 0.85) * 100);
              const livenessScore = Math.round((d.liveness?.liveness_score || 0.75) * 100);
              const risk = d.risk || {};

              // Synthesize both acoustic risk and conversational linguistic threat
              const convRisk = Math.round((prev.conversation?.risk_signal || 0) * 100);
              const acousticRisk = risk.risk_score !== undefined ? risk.risk_score : prev.risk_score;
              const compositeRisk = Math.max(acousticRisk, convRisk);

              let effectiveLevel = risk.risk_level || prev.risk_level;
              let effectiveAction = risk.action || risk.recommended_action || prev.action;
              let effectiveCallStatus = prev.call_status;

              if (compositeRisk >= 80) {
                effectiveLevel = 'CRITICAL';
                effectiveAction = 'BLOCK';
                effectiveCallStatus = 'BLOCKED';
              } else if (compositeRisk >= 50) {
                effectiveLevel = 'HIGH';
                effectiveAction = 'WARN';
                if (effectiveCallStatus !== 'BLOCKED') effectiveCallStatus = 'WARNED';
              } else if (compositeRisk >= 30) {
                effectiveLevel = 'MEDIUM';
                effectiveAction = 'CHALLENGE';
                if (effectiveCallStatus !== 'BLOCKED' && effectiveCallStatus !== 'WARNED') effectiveCallStatus = 'CHALLENGING';
              }

              return {
                ...prev,
                latency_ms: roundtrip > 0 && roundtrip < 500 ? roundtrip : prev.latency_ms,
                voice_authenticity: authenticity,
                speaker_match: speakerScore,
                liveness: livenessScore,
                deepfake_probability: deepfakeProb,
                risk_score: compositeRisk,
                risk_level: effectiveLevel as any,
                action: effectiveAction as any,
                call_status: effectiveCallStatus as any,
                confidence: risk.confidence !== undefined ? risk.confidence : prev.confidence,
                policy_version: risk.policy_version || prev.policy_version,
                vad_active: !!d.vad?.speech_detected,
                explanation: risk.explanation || prev.explanation,
              };
            });
          } else if (msg.type === 'TRANSCRIPT_STORED') {
            setTelemetry((prev) => {
              const convRisk = msg.risk_score !== undefined ? msg.risk_score : 10;
              const compositeRisk = Math.max(prev.risk_score, convRisk);
              const level = convRisk >= 80 ? 'CRITICAL' : (convRisk >= 50 ? 'HIGH' : (convRisk >= 30 ? 'MEDIUM' : 'LOW'));
              const action = convRisk >= 80 ? 'BLOCK' : (convRisk >= 50 ? 'WARN' : (convRisk >= 30 ? 'CHALLENGE' : 'ALLOW'));
              const callStatus = action === 'BLOCK' ? 'BLOCKED' : (action === 'WARN' ? 'WARNED' : (action === 'CHALLENGE' ? 'CHALLENGING' : prev.call_status));
              const threatSignal = `Linguistic Scam Intent: ${msg.intent} (${convRisk}% Risk)`;

              const existingSignals = prev.threat_signals.filter((s) => !s.startsWith('Linguistic'));
              const updatedSignals = convRisk >= 30 ? [threatSignal, ...existingSignals] : existingSignals;

              return {
                ...prev,
                live_transcript: msg.text,
                conversation: {
                  intent: msg.intent || 'ANALYZED',
                  risk_signal: convRisk / 100,
                  evidence: msg.evidence || `Transcribed: "${msg.text}"`,
                  transcript: msg.text,
                },
                risk_score: compositeRisk,
                risk_level: level as any,
                action: action as any,
                call_status: callStatus as any,
                threat_signals: updatedSignals,
                explanation: `Linguistic Threat (${msg.intent}): ${msg.evidence}\nCaller spoken phrase: "${msg.text}"\nAction: ${action}`,
              };
            });
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
  }, [stopAudioStreaming]);

  useEffect(() => {
    connect();
    connectDashboardWs();
    return () => {
      wsRef.current?.close();
      dashboardWsRef.current?.close();
    };
  }, [connect, connectDashboardWs]);

  // Transmit transcript text to FastAPI backend and update local telemetry
  const sendTranscriptText = useCallback((text: string) => {
    const clean = text.trim();
    if (!clean) return;
    lastTransmittedPhraseRef.current = clean;

    const lower = clean.toLowerCase();
    let immediateRisk = 10;
    let immediateIntent = 'NOMINAL';
    let immediateEvidence = `Transcribed caller speech: "${clean}"`;

    const isOtpScam = /(otp|password|passcode|pin code|security code|verify code)/i.test(lower) && /(send|give|tell|share|read out|enter|provide|need)/i.test(lower);
    const isWireUrgent = /(transfer|wire|send money|pay|upi|deposit)/i.test(lower) && /(urgent|immediately|right now|accident|hospital|emergency|police|jail)/i.test(lower);
    const isFinancial = /(transfer|wire|send money|pay|deposit|rupees|dollars|bank account|upi id)/i.test(lower);
    const isOtpMention = /(otp|password|pin code)/i.test(lower);

    if (isOtpScam) {
      immediateRisk = 95;
      immediateIntent = 'OTP_REQUEST';
      immediateEvidence = `CRITICAL FRAUD: Caller demanding authentication OTP/credential: "${clean}"`;
    } else if (isWireUrgent) {
      immediateRisk = 90;
      immediateIntent = 'EMERGENCY_MONEY_REQUEST';
      immediateEvidence = `CRITICAL FRAUD: Emergency coercion financial solicitation: "${clean}"`;
    } else if (isFinancial || isOtpMention) {
      immediateRisk = 65;
      immediateIntent = 'FINANCIAL_REQUEST';
      immediateEvidence = `HIGH RISK: Financial payment / credential discussion: "${clean}"`;
    }

    setTelemetry((prev) => {
      const newScore = Math.max(prev.risk_score, immediateRisk);
      const newLevel = newScore >= 80 ? 'CRITICAL' : (newScore >= 50 ? 'HIGH' : (newScore >= 30 ? 'MEDIUM' : prev.risk_level));
      const newAction = newScore >= 80 ? 'BLOCK' : (newScore >= 50 ? 'WARN' : (newScore >= 30 ? 'CHALLENGE' : prev.action));
      const newCallStatus = newAction === 'BLOCK' ? 'BLOCKED' : (newAction === 'WARN' ? 'WARNED' : (newAction === 'CHALLENGE' ? 'CHALLENGING' : prev.call_status));
      const newSignals = immediateRisk >= 50
        ? [`Linguistic Threat: ${immediateIntent}`, ...prev.threat_signals.filter((s) => !s.startsWith('Linguistic'))]
        : prev.threat_signals;

      return {
        ...prev,
        live_transcript: clean,
        conversation: {
          intent: immediateIntent,
          risk_signal: immediateRisk / 100,
          evidence: immediateEvidence,
          transcript: clean,
        },
        risk_score: newScore,
        risk_level: newLevel as any,
        action: newAction as any,
        call_status: newCallStatus as any,
        threat_signals: newSignals,
        explanation: immediateRisk >= 50
          ? `Linguistic Threat Alert (${immediateIntent}): ${immediateEvidence}\nCaller phrase: "${clean}"`
          : prev.explanation,
      };
    });

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'TRANSCRIPT',
        text: clean,
        is_final: true,
        caller_id: 'MIC_CALLER',
      }));
    }
  }, []);

  // Start / Stop Microphone Stream
  const toggleStreaming = async () => {
    if (isStreaming) {
      // Stop
      if (pendingSpeechTimeoutRef.current) {
        clearTimeout(pendingSpeechTimeoutRef.current);
      }
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
                if (finalTxt.trim()) {
                  if (pendingSpeechTimeoutRef.current) {
                    clearTimeout(pendingSpeechTimeoutRef.current);
                  }
                  sendTranscriptText(finalTxt.trim());
                } else {
                  // Debounce interim words so speech is stored to DB even if final event is delayed
                  if (pendingSpeechTimeoutRef.current) {
                    clearTimeout(pendingSpeechTimeoutRef.current);
                  }
                  pendingSpeechTimeoutRef.current = setTimeout(() => {
                    sendTranscriptText(currentPhrase);
                  }, 900);
                }
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
    stopAudioStreaming,
    sendTranscriptText,
    audioAnalyser: analyserRef.current,
    latestIncomingCall,
    setLatestIncomingCall,
    simulateScenario,
    triggerVerifyIdentity,
    triggerChallenge,
    triggerWarn,
    triggerBlock,
  };
}
