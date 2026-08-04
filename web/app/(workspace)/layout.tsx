import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import AppShell from "@/components/layout/AppShell";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";
import VoiceActionBridge from "@/components/voice/VoiceActionBridge";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <CapabilityAccessProvider>
      <UnifiedChatProvider>
        <VoiceActionBridge />
        <AppShell sidebar={<WorkspaceSidebar />}>
          <CapabilityGate>{children}</CapabilityGate>
        </AppShell>
      </UnifiedChatProvider>
    </CapabilityAccessProvider>
  );
}
