import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import AppShell from "@/components/layout/AppShell";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";
import VoiceActionBridgeMount from "@/components/voice/VoiceActionBridgeMount";
import { StudentNotice } from "@/components/StudentNotice";
import { ChatRuntimeProvider } from "@/features/chat";
import { ReadingProvider } from "@/context/ReadingContext";
import { WatchingProvider } from "@/context/WatchingContext";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <CapabilityAccessProvider>
      <ChatRuntimeProvider>
        <VoiceActionBridgeMount />
        {/* Fork: a student account's one-time notice (school roles, decision 8). */}
        <StudentNotice />
        {/* Above the page on purpose: sending the first message navigates
            /chat → /chat/<id>, which remounts the page. The open document
            must not die with it. */}
        <ReadingProvider>
          <WatchingProvider>
            <AppShell sidebar={<WorkspaceSidebar />}>
              <CapabilityGate>{children}</CapabilityGate>
            </AppShell>
          </WatchingProvider>
        </ReadingProvider>
      </ChatRuntimeProvider>
    </CapabilityAccessProvider>
  );
}
