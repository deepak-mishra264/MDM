import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Brain, CheckCircle2, Play, RotateCcw, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function Strategy() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [strategy, setStrategy] = useState(null);
  const [intent, setIntent] = useState(null);
  const [executing, setExecuting] = useState(false);

  const fetchStrategy = async () => {
    setLoading(true);
    try {
      const [{ data: s }, { data: i }] = await Promise.all([
        api.post(`/agent/strategy/${jobId}`),
        api.get(`/intent/${jobId}`),
      ]);
      setStrategy(s);
      setIntent(i);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Agent could not produce a strategy");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStrategy(); /* eslint-disable-next-line */ }, [jobId]);

  const execute = async () => {
    setExecuting(true);
    try {
      await api.post(`/pipeline/execute/${jobId}`);
      toast.success("Pipeline started · watch the live progress");
      navigate(`/pipeline/${jobId}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Pipeline failed to start");
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-[1100px] mx-auto" data-testid="strategy-page">
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[#5F6368] mb-1">Step 2 of 3</div>
          <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Agent Strategy Summary</h1>
          <p className="text-sm text-[#3C4043] mt-1 max-w-2xl">
            The intent interpreter has converted your plain-English rules into a BigQuery
            execution plan. Review and confirm before running the pipeline.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={fetchStrategy} disabled={loading} className="text-[#1A73E8] hover:bg-[#E8F0FE]" data-testid="regenerate-strategy-btn">
          <RotateCcw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />Regenerate
        </Button>
      </div>

      {/* Info callout */}
      {loading ? (
        <div className="border-l-4 border-[#1A73E8] bg-[#E8F0FE] text-[#1557B0] p-5 rounded-r-md text-sm" data-testid="strategy-loading">
          Asking the agent…
        </div>
      ) : strategy ? (
        <div className="space-y-5 reveal">
          <div className="border-l-4 border-[#1A73E8] bg-[#E8F0FE] text-[#1557B0] p-5 rounded-r-md" data-testid="strategy-summary-callout">
            <div className="flex items-start gap-3">
              <Brain className="h-5 w-5 mt-0.5 shrink-0" />
              <div>
                <div className="font-display font-semibold text-[15px] text-[#1557B0]">Strategy</div>
                <p className="text-[14px] leading-relaxed text-[#202124] mt-1.5">{strategy.summary}</p>
                <div className="flex flex-wrap items-center gap-2 mt-3 text-xs">
                  <Badge className="bg-white text-[#1A73E8] border border-[#1A73E8] hover:bg-white">Backend · {strategy.backend}</Badge>
                  <Badge className="bg-white text-[#188038] border border-[#188038] hover:bg-white">Confidence · {strategy.confidence}</Badge>
                  {strategy.agent_error && (
                    <Badge className="bg-[#FEF7E0] text-[#9C5500] border border-[#FEEFC3] hover:bg-[#FEF7E0]">LLM unavailable · using deterministic fallback</Badge>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Configuration snapshot */}
          <div className="grid md:grid-cols-2 gap-4">
            <div className="bg-white border border-[#DADCE0] rounded-md p-5" data-testid="match-config-card">
              <div className="text-[11px] uppercase tracking-[0.12em] text-[#5F6368] mb-2">Match Columns (used by both engines)</div>
              <ul className="space-y-2 text-sm">
                {(intent?.match_columns || []).map((c) => (
                  <li key={c.name} className="flex items-center justify-between gap-4">
                    <span className="text-[#202124]">{c.name}</span>
                    <Badge className="bg-[#E8F0FE] text-[#1A73E8] hover:bg-[#E8F0FE]">Weight · {c.weight}%</Badge>
                  </li>
                ))}
                {(intent?.match_columns || []).length === 0 && (
                  <li className="text-xs text-[#5F6368]">No columns selected.</li>
                )}
              </ul>
            </div>

            <div className="bg-white border border-[#DADCE0] rounded-md p-5" data-testid="survivorship-breakdown-card">
              <div className="text-[11px] uppercase tracking-[0.12em] text-[#5F6368] mb-2">Survivorship Rules (Agent-Interpreted)</div>
              <ul className="space-y-2.5 text-sm">
                {(strategy.survivorship_breakdown || []).map((s, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <Sparkles className="h-3.5 w-3.5 mt-1 text-[#1A73E8] shrink-0" />
                    <div>
                      <div className="font-medium text-[#202124]">{s.attribute}</div>
                      <div className="text-xs text-[#5F6368]">{s.interpreted_rule}</div>
                    </div>
                  </li>
                ))}
                {(strategy.survivorship_breakdown || []).length === 0 && (
                  <li className="text-xs text-[#5F6368]">No explicit rules — default is most-recent non-null per column.</li>
                )}
              </ul>
            </div>
          </div>

          <div className="flex items-center justify-between bg-white border border-[#DADCE0] rounded-md p-5">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5 text-[#188038]" />
              <div>
                <div className="font-medium text-sm">Ready to execute</div>
                <div className="text-xs text-[#5F6368]">user_intent_store.json is locked. Re-runs reproduce the same logic.</div>
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => navigate(`/configure/${jobId}`)} className="border-[#DADCE0]" data-testid="back-to-configure-btn">
                Back
              </Button>
              <Button
                onClick={execute}
                disabled={executing}
                className="bg-[#1A73E8] hover:bg-[#1557B0] text-white"
                data-testid="confirm-execute-btn"
              >
                <Play className="h-4 w-4 mr-2" />
                {executing ? "Running pipeline…" : "Confirm & Execute"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
