import React, { useState, useEffect, useRef } from 'react';
import { TopNav } from './components/TopNav';
import { CenterPanel } from './components/CenterPanel';
import { RightPanel } from './components/RightPanel';
import { BottomActionBar } from './components/BottomActionBar';
import { ConsentModal } from './components/ConsentModal';
import { SihDemoController } from './components/SihDemoController';
import { IncomingCallScreenModal, type LiveScreenedCall } from './components/IncomingCallScreenModal';
import { useVigilWebSocket } from './hooks/useVigilWebSocket';
import type { SecurityTelemetry } from './types';
import { getUserSession } from './lib/session';

// Synthesizes an emergency dual-tone radar alert without needing external MP3s
const playFraudAlertSiren = () => {
  try {
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioContextClass) return;
    const ctx = new AudioContextClass();
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(920, now);
    osc.frequency.exponentialRampToValueAtTime(460, now + 0.22);
    osc.frequency.setValueAtTime(920, now + 0.28);
    osc.frequency.exponentialRampToValueAtTime(460, now + 0.52);
    gain.gain.setValueAtTime(0.25, now);
    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.58);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.58);
  } catch (err) {
    // AudioContext permission safety catch
  }
};

export const App: React.FC = () => {
  const {
    telemetry,
    isStreaming,
    toggleStreaming,
    sendTranscriptText,
    audioAnalyser,
    latestIncomingCall,
    simulateScenario,
    triggerVerifyIdentity,
    triggerChallenge,
    triggerWarn,
    triggerBlock,
  } = useVigilWebSocket();

  const [demoTelemetry, setDemoTelemetry] = useState<Partial<SecurityTelemetry>>({});
  const activeTelemetry: SecurityTelemetry = { ...telemetry, ...demoTelemetry };

  const [hasConsent, setHasConsent] = useState<boolean>(() => {
    return localStorage.getItem('vigil_mic_consent') === 'true';
  });
  const [showConsentModal, setShowConsentModal] = useState<boolean>(false);
  const [showIncomingCallScreen, setShowIncomingCallScreen] = useState<boolean>(false);
  const [latestLiveCall, setLatestLiveCall] = useState<LiveScreenedCall | null>(null);
  const [showCallAlertBanner, setShowCallAlertBanner] = useState<boolean>(false);

  // Ref to track last processed call without closure re-renders
  const lastAlertedTimestampRef = useRef<string | null>(null);

  // Initial one-shot load of call screening history when page loads (zero polling)
  useEffect(() => {
    let isMounted = true;
    const fetchInitialCall = async () => {
      try {
        const session = getUserSession();
        const res = await fetch(`/api/v1/screening/live?user_id=${encodeURIComponent(session.userId)}`);
        if (res.ok && isMounted) {
          const data = await res.json();
          if (data.latest_call) {
            setLatestLiveCall(data.latest_call);
          }
        }
      } catch (err) {
        // silent
      }
    };
    fetchInitialCall();
    return () => {
      isMounted = false;
    };
  }, []);

  // Real-time Event-Driven WebSocket Push for Incoming Calls (ZERO POLLING)
  useEffect(() => {
    if (!latestIncomingCall) return;

    const mappedCall: LiveScreenedCall = {
      timestamp: latestIncomingCall.timestamp || new Date().toISOString(),
      phone_number: latestIncomingCall.phone_number || '',
      normalized_number: latestIncomingCall.normalized_phone_number || latestIncomingCall.phone_number || '',
      masked_phone: latestIncomingCall.masked_phone || latestIncomingCall.phone_number || '',
      caller_name: latestIncomingCall.caller_name || 'Incoming Caller',
      company_name: latestIncomingCall.company || null,
      company_badge: latestIncomingCall.company_verification_status || null,
      verification_status: latestIncomingCall.company_verification_status || 'UNVERIFIED',
      trust_status: latestIncomingCall.contact_known ? 'contact' : 'untrusted',
      risk_score: latestIncomingCall.initial_risk !== undefined ? latestIncomingCall.initial_risk : (latestIncomingCall.risk_score || 15),
      risk_level: latestIncomingCall.risk_level || 'LOW',
      action: latestIncomingCall.recommended_action || latestIncomingCall.action || 'MONITOR',
      reasons: latestIncomingCall.threat_signals || [],
      voice_deepfake_pct: latestIncomingCall.voice_deepfake_pct || 0,
      voice_identity_pct: latestIncomingCall.voice_identity_pct || 0,
      voice_liveness_pct: latestIncomingCall.voice_liveness_pct || 0,
      warning_banner: latestIncomingCall.warning_banner || (
        latestIncomingCall.recommended_action === 'BLOCK' || latestIncomingCall.action === 'BLOCK'
          ? 'Android Telecom dropped call with busy signal before ringing.'
          : '⚠️ Treat as potentially compromised: Phone identity does not verify voice identity.'
      ),
      calls_summary_total: latestIncomingCall.previous_calls || 0,
      calls_summary_today: latestIncomingCall.calls_today || 0,
      call_id: latestIncomingCall.call_id,
      caller_type: latestIncomingCall.caller_type,
      contact_known: latestIncomingCall.contact_known,
      speaker_verification_status: latestIncomingCall.speaker_verification_status || 'WAITING',
      deepfake_detection_status: latestIncomingCall.deepfake_detection_status || 'WAITING',
      liveness_status: latestIncomingCall.liveness_status || 'WAITING',
      cellular_audio_available: latestIncomingCall.cellular_audio_available ?? false,
      call_transport: latestIncomingCall.call_transport || 'CELLULAR',
      last_call_timestamp: latestIncomingCall.last_call_timestamp,
    };

    setLatestLiveCall(mappedCall);
    lastAlertedTimestampRef.current = mappedCall.timestamp;
    setShowCallAlertBanner(true);

    // Check if call represents a high risk attack requiring immediate HUD modal & audio siren
    const isCriticalThreat = mappedCall.action === 'BLOCK' || 
                            mappedCall.action === 'TERMINATE' ||
                            mappedCall.risk_score >= 50 || 
                            mappedCall.risk_level === 'CRITICAL';

    if (isCriticalThreat) {
      setShowIncomingCallScreen(true);
      playFraudAlertSiren();

      setDemoTelemetry({
        call_status: mappedCall.action === 'TERMINATE' ? 'TERMINATED' : 'BLOCKED',
        risk_score: mappedCall.risk_score,
        risk_level: (mappedCall.risk_level as any) || 'CRITICAL',
        action: (mappedCall.action as any) || 'BLOCK',
        voice_authenticity: mappedCall.voice_identity_pct || 12,
        deepfake_probability: mappedCall.voice_deepfake_pct || 96,
        liveness: mappedCall.voice_liveness_pct || 32,
        threat_signals: mappedCall.reasons.length > 0 ? mappedCall.reasons : [
          'Known digital arrest scam pattern',
          'Carrier STIR/SHAKEN signature spoofed/absent',
          'Police/Cyber Crime impersonation',
          'Automated drop by Telecom Mode B',
        ],
        explanation: `🚨 LIVE FRAUD CALL INTERCEPTED: ${mappedCall.caller_name} (${mappedCall.masked_phone}). Telecom Mode B: Dropped and auto-rejected before ringing.`,
        live_transcript: `🚨 CALLER: "${mappedCall.caller_name}" calling subscriber. System rejected call automatically.`,
      });
    }
  }, [latestIncomingCall]);

  const handleTriggerLiveFraudCall = async () => {
    try {
      const session = getUserSession();
      const res = await fetch('/api/v1/screening/trigger-fraud-call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: session.userId,
          device_id: session.deviceUuid,
          installation_id: session.installationId,
        })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.call) {
          setLatestLiveCall(data.call);
          lastAlertedTimestampRef.current = data.call.timestamp;
          setShowIncomingCallScreen(true);
          setShowCallAlertBanner(true);
          playFraudAlertSiren();
          setDemoTelemetry({
            call_status: 'BLOCKED',
            risk_score: 100,
            risk_level: 'CRITICAL',
            action: 'BLOCK',
            voice_authenticity: 12,
            deepfake_probability: 96,
            liveness: 32,
            threat_signals: data.call.reasons,
            explanation: `🚨 LIVE FRAUD CALL INTERCEPTED: ${data.call.caller_name} (${data.call.masked_phone}). Telecom Mode B: Dropped and auto-rejected before ringing.`,
            live_transcript: `🚨 CALLER: "${data.call.caller_name}" calling subscriber. System rejected call automatically.`,
          });
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleToggleStreamWithConsent = () => {
    if (!isStreaming && !hasConsent) {
      setShowConsentModal(true);
    } else {
      toggleStreaming();
    }
  };

  const handleConfirmConsent = () => {
    localStorage.setItem('vigil_mic_consent', 'true');
    setHasConsent(true);
    setShowConsentModal(false);
    toggleStreaming();
  };

  return (
    <div className="min-h-screen w-full flex flex-col bg-[#06090e] text-slate-200 selection:bg-cyan-500 selection:text-black">
      {/* 1. TOP BAR */}
      <TopNav
        connectionStatus={activeTelemetry.connection_status}
        latencyMs={activeTelemetry.latency_ms}
        modelVersion={activeTelemetry.model_version}
        policyVersion={activeTelemetry.policy_version || '2026.09.1-production'}
        isStreaming={isStreaming}
        onOpenIncomingCallScreen={() => setShowIncomingCallScreen(true)}
        onTriggerLiveFraudCall={handleTriggerLiveFraudCall}
        latestCall={latestLiveCall}
      />

      {/* Real-time Phone Screening Alert Banner */}
      {showCallAlertBanner && latestLiveCall && (
        <div className={`w-full px-6 py-2.5 flex items-center justify-between font-mono text-xs border-b animate-in slide-in-from-top ${
          latestLiveCall.action === 'BLOCK'
            ? 'bg-rose-950/95 border-rose-600 text-rose-200 shadow-[0_0_20px_rgba(244,63,94,0.3)]'
            : 'bg-emerald-950/95 border-emerald-600 text-emerald-200'
        }`}>
          <div className="flex items-center gap-2.5 flex-wrap">
            <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping" />
            <strong className="tracking-wider uppercase">⚡ SMARTPHONE TELEPHONY SCREENING ALERT:</strong>
            <span className="font-bold text-white">{latestLiveCall.caller_name}</span>
            <span className="text-cyan-300">({latestLiveCall.masked_phone})</span>
            <span className={`px-2 py-0.5 rounded font-bold ${
              latestLiveCall.action === 'BLOCK' ? 'bg-black/60 text-rose-300 border border-rose-800' : 'bg-black/60 text-emerald-300'
            }`}>
              VERDICT: {latestLiveCall.action} ({latestLiveCall.risk_score} pts)
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowIncomingCallScreen(true)}
              className="px-3 py-1 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-bold cursor-pointer transition-all active:scale-95 text-[11px]"
            >
              INSPECT IN HUD
            </button>
            <button
              onClick={() => setShowCallAlertBanner(false)}
              className="p-1 text-slate-400 hover:text-white transition-colors cursor-pointer"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* 2. MAIN OPERATIONS DASHBOARD GRID */}
      <main className="flex-1 w-full max-w-7xl mx-auto p-4 md:p-6 flex flex-col gap-6">
        {/* SIH DEMO MODE CONTROLLER */}
        <SihDemoController
          telemetry={activeTelemetry}
          onUpdateTelemetry={(newTel) => setDemoTelemetry((prev) => ({ ...prev, ...newTel }))}
        />

        <div className="flex flex-col lg:flex-row gap-6">
          {/* CENTER PANEL: CALL STATUS, GAUGES, RISK SCORE, OSCILLOSCOPE */}
          <CenterPanel
            callStatus={activeTelemetry.call_status}
            voiceAuthenticity={activeTelemetry.voice_authenticity}
            speakerMatch={activeTelemetry.speaker_match}
            liveness={activeTelemetry.liveness}
            deepfakeProbability={activeTelemetry.deepfake_probability}
            riskScore={activeTelemetry.risk_score}
            riskLevel={activeTelemetry.risk_level}
            action={activeTelemetry.action}
            confidence={activeTelemetry.confidence}
            vadActive={activeTelemetry.vad_active}
            isStreaming={isStreaming}
            onToggleStream={handleToggleStreamWithConsent}
            audioAnalyser={audioAnalyser}
            waveformSample={activeTelemetry.waveform_sample}
            explanation={activeTelemetry.explanation}
            callerTranscript={activeTelemetry.live_transcript || activeTelemetry.conversation?.transcript}
            onSendTranscript={sendTranscriptText}
            activeCall={activeTelemetry.active_call}
          />

          {/* RIGHT PANEL: THREAT SIGNALS, TIMELINE, CONVERSATION INTELLIGENCE */}
          <RightPanel
            threatSignals={activeTelemetry.threat_signals}
            timeline={activeTelemetry.timeline}
            conversation={activeTelemetry.conversation}
            activeChallenge={activeTelemetry.active_challenge}
          />
        </div>
      </main>

      {/* 3. BOTTOM CONTROL & INTERVENTION BAR */}
      <BottomActionBar
        onVerifyIdentity={triggerVerifyIdentity}
        onChallenge={triggerChallenge}
        onWarn={triggerWarn}
        onBlock={triggerBlock}
        onSimulateScenario={simulateScenario}
      />

      {/* 4. EXPLICIT MICROPHONE CONSENT MODAL */}
      <ConsentModal
        isOpen={showConsentModal}
        onConsent={handleConfirmConsent}
        onCancel={() => setShowConsentModal(false)}
      />

      {/* 5. VIGIL-AI INCOMING CALL SCREEN & REPUTATION HUD MODAL */}
      <IncomingCallScreenModal
        isOpen={showIncomingCallScreen}
        onClose={() => setShowIncomingCallScreen(false)}
        latestCall={latestLiveCall}
        activeTelemetry={activeTelemetry}
      />
    </div>
  );
};

export default App;
