import { Routes, Route } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { OverviewPage } from "@/pages/OverviewPage";
import { LBrainPage } from "@/pages/LBrainPage";
import { MemoryPage } from "@/pages/MemoryPage";
import { ActionsPage } from "@/pages/ActionsPage";
import { AuditPage } from "@/pages/AuditPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="memory" element={<MemoryPage />} />
        <Route path="lbrain" element={<LBrainPage />} />
        <Route path="actions" element={<ActionsPage />} />
        <Route path="audit" element={<AuditPage />} />
      </Route>
    </Routes>
  );
}
