import React from 'react';
import { TopNav } from './components/TopNav';
import { CenterPanel } from './components/CenterPanel';
import { RightPanel } from './components/RightPanel';
import { BottomActionBar } from './components/BottomActionBar';
import { useVigilWebSocket } from './hooks/useVigilWebSocket';

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

  return (
    <div className="min-h-screen w-full flex flex-col bg-[#06090e] text-slate-200 selection:bg-cyan-500 selection:text-black">
      {/* 1. TOP BAR */}
      <TopNav
        connectionStatus={telemetry.connection_status}
        latencyMs={telemetry.latency_ms}
        modelVersion={telemetry.model_version}
        policyVersion={telemetry.policy_version || '2026.09.1-production'}
        isStreaming={isStreaming}
      />

      {/* 2. MAIN OPERATIONS DASHBOARD GRID */}
      <main className="flex-1 w-full max-w-7xl mx-auto p-4 md:p-6 flex flex-col lg:flex-row gap-6">
        {/* CENTER PANEL: CALL STATUS, GAUGES, RISK SCORE, OSCILLOSCOPE */}
        <CenterPanel
          callStatus={telemetry.call_status}
          voiceAuthenticity={telemetry.voice_authenticity}
          speakerMatch={telemetry.speaker_match}
          liveness={telemetry.liveness}
          deepfakeProbability={telemetry.deepfake_probability}
          riskScore={telemetry.risk_score}
          riskLevel={telemetry.risk_level}
          action={telemetry.action}
          confidence={telemetry.confidence}
          vadActive={telemetry.vad_active}
          isStreaming={isStreaming}
          onToggleStream={toggleStreaming}
          audioAnalyser={audioAnalyser}
        />

        {/* RIGHT PANEL: THREAT SIGNALS, TIMELINE, CONVERSATION INTELLIGENCE */}
        <RightPanel
          threatSignals={telemetry.threat_signals}
          timeline={telemetry.timeline}
          conversation={telemetry.conversation}
          activeChallenge={telemetry.active_challenge}
        />
      </main>

      {/* 3. BOTTOM CONTROL & INTERVENTION BAR */}
      <BottomActionBar
        onVerifyIdentity={triggerVerifyIdentity}
        onChallenge={triggerChallenge}
        onWarn={triggerWarn}
        onBlock={triggerBlock}
        onSimulateScenario={simulateScenario}
      />
    </div>
  );
};

export default App;
