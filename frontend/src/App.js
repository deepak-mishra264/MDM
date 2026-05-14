import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Layout from "@/components/Layout";
import Home from "@/pages/Home";
import Configure from "@/pages/Configure";
import Strategy from "@/pages/Strategy";
import Pipeline from "@/pages/Pipeline";
import Results from "@/pages/Results";
import IdentitySearch from "@/pages/IdentitySearch";
import SQLViewer from "@/pages/SQLViewer";
import Audit from "@/pages/Audit";
import Settings from "@/pages/Settings";

export default function App() {
  return (
    <div className="App" data-testid="searce-mdm-app">
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Home />} />
            <Route path="/configure/:jobId" element={<Configure />} />
            <Route path="/strategy/:jobId" element={<Strategy />} />
            <Route path="/pipeline/:jobId" element={<Pipeline />} />
            <Route path="/results/:jobId" element={<Results />} />
            <Route path="/search/:jobId" element={<IdentitySearch />} />
            <Route path="/sql/:jobId" element={<SQLViewer />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="bottom-right" richColors />
    </div>
  );
}
