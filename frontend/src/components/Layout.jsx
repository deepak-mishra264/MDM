import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import {
  Home, Sliders, Brain, GitBranch, Database,
  Search, Code2, ScrollText, Settings as SettingsIcon, Cloud
} from "lucide-react";
import { api } from "@/lib/api";
import Logo from "@/components/Logo";

const NAV = [
  { to: "/", label: "Hero Upload", icon: Home, testid: "nav-home", exact: true },
  { to: "/configure", label: "Configure", icon: Sliders, testid: "nav-configure", needsJob: true },
  { to: "/strategy", label: "Agent Strategy", icon: Brain, testid: "nav-strategy", needsJob: true },
  { to: "/pipeline", label: "Pipeline", icon: GitBranch, testid: "nav-pipeline", needsJob: true },
  { to: "/results", label: "Results", icon: Database, testid: "nav-results", needsJob: true },
  { to: "/search", label: "Identity Search", icon: Search, testid: "nav-search", needsJob: true },
  { to: "/sql", label: "BigQuery SQL", icon: Code2, testid: "nav-sql", needsJob: true },
  { to: "/audit", label: "Audit Trail", icon: ScrollText, testid: "nav-audit" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, testid: "nav-settings" },
];

export default function Layout() {
  const { jobId } = useParams();
  const location = useLocation();
  const [health, setHealth] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get("/health");
        if (!cancelled) setHealth(data);
      } catch {}
    })();
    return () => { cancelled = true; };
  }, []);

  // Try to grab a jobId out of the current path if not available via params
  const segs = location.pathname.split("/").filter(Boolean);
  const activeJob = jobId || (segs.length >= 2 ? segs[1] : "");
  const isLive = health?.mode === "live";

  return (
    <div className="min-h-screen flex bg-[#F8F9FA] text-[#202124]" data-testid="app-layout">
      {/* Sidebar */}
      <aside className="w-64 border-r border-[#DADCE0] bg-white flex flex-col" data-testid="sidebar">
        <div className="px-5 py-5 border-b border-[#DADCE0] flex items-center gap-2.5">
          <Logo className="h-7 w-7" />
          <div className="leading-tight">
            <div className="font-display text-[17px] font-bold tracking-tight">Searce MDM</div>
            <div className="text-[11px] text-[#5F6368] uppercase tracking-widest" data-testid="mode-tag">
              v4.0 · {isLive ? "Live" : "Preview"}
            </div>
          </div>
        </div>
        <nav className="flex-1 py-3 space-y-0.5" aria-label="Primary">
          {NAV.map((item) => {
            const Icon = item.icon;
            const target = item.needsJob && activeJob ? `${item.to}/${activeJob}` : item.to;
            const disabled = item.needsJob && !activeJob;
            return (
              <NavLink
                key={item.to}
                to={target}
                end={item.exact}
                className={({ isActive }) =>
                  [
                    "flex items-center gap-3 mx-2 px-3 py-2 rounded-md text-sm transition-colors duration-200",
                    isActive && !disabled
                      ? "bg-[#E8F0FE] text-[#1A73E8] font-semibold"
                      : "text-[#3C4043] hover:bg-[#F1F3F4]",
                    disabled ? "opacity-40 pointer-events-none" : "",
                  ].join(" ")
                }
                data-testid={item.testid}
              >
                <Icon className="h-4 w-4" strokeWidth={1.8} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
        <div className="p-4 border-t border-[#DADCE0] text-[11px] text-[#5F6368]">
          <div className="flex items-center gap-2">
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${isLive ? "bg-[#188038]" : "bg-[#F29900]"}`} />
            <span data-testid="mode-banner">
              {isLive ? "Live mode · GCP active" : "Preview mode · GCP stubbed"}
            </span>
          </div>
          <div className="mt-1 truncate">
            {isLive
              ? `Project · ${health?.gcp_project || "—"}`
              : "Vertex AI: add creds to go live"}
          </div>
        </div>
      </aside>

      {/* Content */}
      <main className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 px-6 md:px-8 border-b border-[#DADCE0] bg-white flex items-center justify-between" data-testid="topbar">
          <div className="flex items-center gap-2 text-sm text-[#5F6368]">
            <Cloud className="h-4 w-4" />
            <span className="font-medium text-[#202124]">Identity Intelligence Portal</span>
            {activeJob && (
              <>
                <span className="text-[#BDC1C6]">/</span>
                <span className="mono text-xs px-2 py-0.5 rounded bg-[#F1F3F4] text-[#3C4043]" data-testid="active-job-id">
                  job · {activeJob}
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs text-[#5F6368]">
            <span className="hidden sm:inline">Agent-Driven · BigQuery-Ready</span>
          </div>
        </header>
        <div className="flex-1 overflow-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
