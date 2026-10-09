import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Route, Routes, useNavigate } from "react-router";
import { ConnectDialog } from "./components/ConnectDialog";
import { Sidebar } from "./components/Sidebar";
import { AssistantPage } from "./features/assistant/AssistantPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { AgentPage } from "./features/agent/AgentPage";

function Home({ onConnect }: { onConnect: () => void }) {
  return (
    <div className="empty">
      <div>
        <h2>Debug any A2A agent</h2>
        <p style={{ marginBottom: 16 }}>Connect an agent to chat with it, inspect every request and check it against the spec.</p>
        <button className="btn primary" onClick={onConnect}>
          Connect an agent
        </button>
        <p className="no" style={{ marginTop: 14, fontSize: 12.5 }}>
          No agent handy? Run <span className="mono">a2a-workbench fixtures</span> and connect http://127.0.0.1:9999
        </p>
      </div>
    </div>
  );
}

function Shell() {
  const [connecting, setConnecting] = useState(false);
  const navigate = useNavigate();
  const open = () => setConnecting(true);
  return (
    <div className="app">
      <Sidebar onConnect={open} />
      <main className="main">
        <Routes>
          <Route path="/" element={<Home onConnect={open} />} />
          <Route path="/agents/:agentId/:tab?" element={<AgentPage />} />
          <Route path="/assistant/:sessionId?" element={<AssistantPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
      <ConnectDialog
        open={connecting}
        onOpenChange={setConnecting}
        onConnected={(agent) => {
          setConnecting(false);
          navigate(`/agents/${agent.id}`);
        }}
      />
    </div>
  );
}

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });

/** The whole single-page application. */
export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
