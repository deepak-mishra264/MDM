import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, Loader2, Circle, XCircle, ArrowRight, AlertTriangle, MinusCircle } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

const STATE_ICON = {
  pending: Circle,
  running: Loader2,
  done: CheckCircle2,
  failed: XCircle,
  skipped: MinusCircle,
};
const STATE_COLOR = {
  pending: "text-[#BDC1C6]",
  running: "text-[#1A73E8]",
  done: "text-[#188038]",
  failed: "text-[#D93025]",
  skipped: "text-[#9C5500]",
};
const STATE_BG = {
  pending: "bg-[#F1F3F4] border-[#DADCE0]",
  running: "bg-[#E8F0FE] border-[#1A73E8]",
  done: "bg-[#E6F4EA] border-[#CEEAD6]",
  failed: "bg-[#FCE8E6] border-[#F8D7DA]",
  skipped: "bg-[#FEF7E0] border-[#FEEFC3]",
};

export default function Pipeline() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [progress, setProgress] = useState(null);
  const timer = useRef(null);

  const fetchProgress = async () => {
    try {
      const { data } = await api.get(`/pipeline/progress/${jobId}`);
      setProgress(data);
      if (data.state === "complete" || data.state === "failed") {
        if (timer.current) { clearInterval(timer.current); timer.current = null; }
      }
    } catch (e) {/* ignore */ }
  };

  useEffect(() => {
    fetchProgress();
    timer.current = setInterval(fetchProgress, 800);
    return () => { if (timer.current) clearInterval(timer.current); };
    // eslint-disable-next-line
  }, [jobId]);

  const stages = progress?.stages || [];
  const topState = progress?.state || "idle";
  const complete = topState === "complete";
  const failed = topState === "failed";
  const stats = stages.find((s) => s.key === "complete")?.detail || {};

  return (
    <div className="p-6 md:p-8 max-w-[1100px] mx-auto" data-testid="pipeline-page">
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[#5F6368] mb-1">Step 3 of 3</div>
          <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Pipeline Execution</h1>
          <p className="text-sm text-[#3C4043] mt-1 max-w-2xl">
            The agent walks through deterministic matching, probabilistic scoring,
            vector embeddings, clustering, survivorship and BigQuery execution.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => navigate(`/sql/${jobId}`)}
            disabled={!complete}
            className="border-[#DADCE0] text-[#1A73E8] hover:bg-[#E8F0FE]"
            data-testid="view-sql-btn"
          >
            View Generated SQL
          </Button>
          <Button
            onClick={() => navigate(`/results/${jobId}`)}
            disabled={!complete}
            className="bg-[#1A73E8] hover:bg-[#1557B0] text-white"
            data-testid="view-results-btn"
          >
            View Curated Results
            <ArrowRight className="h-4 w-4 ml-2" />
          </Button>
        </div>
      </div>

      {/* Status banner */}
      <div className={`border rounded-md p-4 mb-5 ${
        failed ? "bg-[#FCE8E6] border-[#F8D7DA] text-[#9C2517]"
        : complete ? "bg-[#E6F4EA] border-[#CEEAD6] text-[#0E5E2B]"
        : "bg-[#E8F0FE] border-[#1A73E8] text-[#1557B0]"
      }`} data-testid="pipeline-status-banner">
        <div className="flex items-center gap-3">
          {failed ? <XCircle className="h-5 w-5" /> :
           complete ? <CheckCircle2 className="h-5 w-5" /> :
           <Loader2 className="h-5 w-5 animate-spin" />}
          <div className="flex-1">
            <div className="font-display font-semibold text-sm">
              {failed ? "Pipeline failed"
               : complete ? "Pipeline complete"
               : topState === "idle" ? "Idle — execute from Agent Strategy step"
               : "Pipeline running…"}
            </div>
            {complete && (
              <div className="text-xs mt-0.5 opacity-90">
                {stats.unique_masters || 0} masters · {stats.duplicate_suspects || 0} suspects
                · {stats.deterministic_matches || 0} deterministic · {stats.probabilistic_matches || 0} probabilistic
                · BigQuery: <span className="mono">{stats.bq_state || "stubbed_local"}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Stage timeline */}
      <div className="bg-white border border-[#DADCE0] rounded-md p-2" data-testid="pipeline-timeline">
        {stages.map((s, idx) => {
          const Icon = STATE_ICON[s.state] || Circle;
          const durationMs =
            s.started_at && s.finished_at
              ? new Date(s.finished_at) - new Date(s.started_at)
              : null;
          return (
            <div
              key={s.key}
              className={`flex gap-4 items-start p-4 border rounded-md mb-1.5 last:mb-0 ${STATE_BG[s.state]}`}
              data-testid={`stage-${s.key}`}
            >
              <div className="flex flex-col items-center mt-0.5">
                <div className={`h-8 w-8 rounded-full bg-white border flex items-center justify-center ${STATE_COLOR[s.state]} border-current`}>
                  <Icon className={`h-4 w-4 ${s.state === "running" ? "animate-spin" : ""}`} />
                </div>
                {idx < stages.length - 1 && (
                  <div className={`w-px flex-1 mt-1 ${s.state === "done" ? "bg-[#188038]" : "bg-[#DADCE0]"}`} style={{ minHeight: 18 }} />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-display font-semibold text-sm text-[#202124]">
                      {s.label}
                    </div>
                    <StageDetail stage={s} />
                  </div>
                  <div className="text-[11px] text-[#5F6368] mono whitespace-nowrap">
                    {s.state === "running" && "running…"}
                    {durationMs != null && `${Math.max(durationMs, 1)} ms`}
                    {s.state === "pending" && "pending"}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StageDetail({ stage }) {
  const d = stage.detail || {};
  const items = [];
  if (stage.key === "validating") {
    if (d.deterministic) items.push(`Key: ${(d.deterministic || []).join(", ") || "—"}`);
    if (d.probabilistic) items.push(`Suspect-Score: ${(d.probabilistic || []).join(", ") || "—"}`);
    if (d.rules != null) items.push(`${d.rules} survivorship rule(s)`);
  } else if (stage.key === "standardizing") {
    if (d.rows != null) items.push(`${d.rows} rows normalized`);
  } else if (stage.key === "deterministic") {
    if (d.matches != null) items.push(`${d.matches} exact-match pair(s) found`);
    if (d.keys) items.push(`on ${(d.keys || []).join(", ")}`);
  } else if (stage.key === "probabilistic") {
    if (d.matches != null) items.push(`${d.matches} fuzzy pair(s) ≥ threshold`);
    if (d.attrs) items.push(`on ${(d.attrs || []).join(", ")}`);
  } else if (stage.key === "embedding") {
    if (d.note) items.push(d.note);
  } else if (stage.key === "clustering") {
    if (d.clusters != null) items.push(`${d.clusters} enterprise_id cluster(s) formed`);
  } else if (stage.key === "survivorship") {
    if (d.masters != null) items.push(`${d.masters} golden record(s) built`);
    if (d.rules_applied != null) items.push(`${d.rules_applied} rule(s) applied`);
  } else if (stage.key === "sql") {
    if (d.layers) items.push(`Layers: ${d.layers.join(", ")}`);
  } else if (stage.key === "bigquery") {
    if (d.jobs) items.push(`BQ jobs: ${d.jobs.join(", ")}`);
    if (d.note) items.push(d.note);
    if (d.error) items.push(`Error: ${d.error}`);
  } else if (stage.key === "complete") {
    if (d.unique_masters != null) items.push(`${d.unique_masters} masters · ${d.duplicate_suspects} suspects`);
  }
  if (stage.state === "failed" && d.error) {
    return (
      <div className="text-xs text-[#9C2517] mt-1 flex items-center gap-1.5">
        <AlertTriangle className="h-3.5 w-3.5" />{d.error}
      </div>
    );
  }
  if (!items.length) return null;
  return <div className="text-xs text-[#5F6368] mt-1">{items.join(" · ")}</div>;
}
