import React, { useState } from 'react';
import { TopNav } from './components/TopNav';
import { CenterPanel } from './components/CenterPanel';
import { RightPanel } from './components/RightPanel';
import { BottomActionBar } from './components/BottomActionBar';
import { ConsentModal } from './components/ConsentModal';
import { SihDemoController } from './components/SihDemoController';
import { useVigilWebSocket } from './hooks/useVigilWebSocket';
import type { SecurityTelemetry } from './types';

export const App: React.FC = () => {
  const {
    telemetry,
    isStreaming,
    toggleStreaming,
    audioAnalyser,
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
      />

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
    </div>
  );
};

export default App;
