import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowRight, Save, Equal, Wand2, Info } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";

const DEFAULT_INTENT = "If multiple values exist, pick the most recent non-null value (tie-break by frequency).";

export default function Configure() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [rows, setRows] = useState([]);
  const [threshold] = useState(0.75);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const { data } = await api.get(`/jobs/${jobId}`);
        if (!active) return;
        setJob(data);
        // Initialize attribute rows
        const init = data.columns.map((c) => ({
          name: c,
          match_type: /email|id$/i.test(c) ? "deterministic" : "probabilistic",
          weight: 0,
          survivorship_intent:
            /phone|mobile/i.test(c)
              ? "If multiple phone numbers exist, pick the one that appears most often, but if there is a tie, pick the most recent record."
              : /name/i.test(c)
              ? "Pick the longest non-null value (treat as canonical full name)."
              : /city|country|address/i.test(c)
              ? "Pick the most frequent value across the cluster."
              : DEFAULT_INTENT,
        }));
        // Auto-distribute weights across probabilistic
        const prob = init.filter((a) => a.match_type === "probabilistic");
        const w = prob.length ? Math.floor(100 / prob.length) : 0;
        let remainder = 100 - w * prob.length;
        const result = init.map((a) => {
          if (a.match_type === "probabilistic") {
            const extra = remainder > 0 ? 1 : 0;
            remainder -= extra;
            return { ...a, weight: w + extra };
          }
          return { ...a, weight: 0 };
        });
        setRows(result);
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Job not found");
        navigate("/");
      }
    })();
    return () => { active = false; };
  }, [jobId, navigate]);

  const probTotal = useMemo(
    () => rows.filter((r) => r.match_type === "probabilistic").reduce((s, r) => s + Number(r.weight || 0), 0),
    [rows]
  );

  const update = (i, patch) => {
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  };

  const setMatchType = (i, type) => {
    setRows((rs) => {
      const next = rs.map((r, idx) => (idx === i ? { ...r, match_type: type, weight: type === "probabilistic" ? r.weight : 0 } : r));
      // If switching ON probabilistic and weights total != 100, give it a starting share
      return next;
    });
  };

  const normalize = () => {
    const prob = rows.filter((r) => r.match_type === "probabilistic");
    if (!prob.length) return;
    const base = Math.floor(100 / prob.length);
    let rem = 100 - base * prob.length;
    setRows((rs) => rs.map((r) => {
      if (r.match_type !== "probabilistic") return { ...r, weight: 0 };
      const add = rem > 0 ? 1 : 0;
      rem -= add;
      return { ...r, weight: base + add };
    }));
    toast.success("Weights normalized to 100%");
  };

  const onSave = async () => {
    if (rows.filter((r) => r.match_type === "probabilistic").length > 0 && Math.abs(probTotal - 100) > 0.01) {
      toast.error(`Probabilistic weights must total 100 (currently ${probTotal})`);
      return;
    }
    setSaving(true);
    try {
      await api.post("/intent/save", { job_id: jobId, attributes: rows, threshold });
      toast.success("Intent saved · user_intent_store.json updated");
      navigate(`/strategy/${jobId}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!job) {
    return <div className="p-8 text-sm text-[#5F6368]" data-testid="configure-loading">Loading job…</div>;
  }

  return (
    <div className="p-6 md:p-8 max-w-[1280px] mx-auto" data-testid="configure-page">
      <div className="flex items-start justify-between gap-6 mb-6">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[#5F6368] mb-1">Step 1 of 3</div>
          <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Configure Attributes</h1>
          <p className="text-sm text-[#3C4043] mt-1 max-w-2xl">
            Choose which columns drive matching, set their weights, and describe survivorship
            logic in plain English. Probabilistic weights must total <strong>100</strong>.
          </p>
        </div>
        <div className="text-right text-xs text-[#5F6368] shrink-0">
          <div>File · <span className="mono text-[#202124]">{job.filename}</span></div>
          <div>Rows · {job.row_count?.toLocaleString()} · Columns · {job.columns?.length}</div>
        </div>
      </div>

      <div className="bg-white border border-[#DADCE0] rounded-md overflow-hidden">
        <div className="grid grid-cols-12 px-4 py-2.5 bg-[#F1F3F4] text-[11px] font-semibold text-[#5F6368] uppercase tracking-[0.06em] border-b border-[#DADCE0]">
          <div className="col-span-2">Attribute</div>
          <div className="col-span-2">Match Type</div>
          <div className="col-span-3">Weight (Probabilistic)</div>
          <div className="col-span-5">Survivorship Intent (Plain English)</div>
        </div>
        {rows.map((r, i) => (
          <div
            key={r.name}
            className="grid grid-cols-12 gap-4 items-start px-4 py-3 border-b border-[#DADCE0] last:border-b-0 hover:bg-[#F8F9FA] transition-colors"
            data-testid={`attribute-row-${r.name}`}
          >
            <div className="col-span-2 pt-2">
              <div className="font-medium text-sm text-[#202124]">{r.name}</div>
              <div className="text-xs text-[#5F6368] mono mt-0.5 truncate" title={job.sample?.[0]?.[r.name] || ""}>
                e.g. {job.sample?.[0]?.[r.name] || "—"}
              </div>
            </div>

            <div className="col-span-2 pt-1.5 space-y-1.5">
              <button
                onClick={() => setMatchType(i, "deterministic")}
                className={`w-full text-left text-xs px-2.5 py-1.5 rounded border ${
                  r.match_type === "deterministic"
                    ? "border-[#1A73E8] bg-[#E8F0FE] text-[#1A73E8]"
                    : "border-[#DADCE0] text-[#3C4043] hover:bg-[#F8F9FA]"
                }`}
                data-testid={`match-deterministic-${r.name}`}
              >
                <Equal className="inline h-3 w-3 mr-1.5" />Deterministic
              </button>
              <button
                onClick={() => setMatchType(i, "probabilistic")}
                className={`w-full text-left text-xs px-2.5 py-1.5 rounded border ${
                  r.match_type === "probabilistic"
                    ? "border-[#1A73E8] bg-[#E8F0FE] text-[#1A73E8]"
                    : "border-[#DADCE0] text-[#3C4043] hover:bg-[#F8F9FA]"
                }`}
                data-testid={`match-probabilistic-${r.name}`}
              >
                <Wand2 className="inline h-3 w-3 mr-1.5" />Probabilistic
              </button>
              <button
                onClick={() => setMatchType(i, "none")}
                className={`w-full text-left text-xs px-2.5 py-1.5 rounded border ${
                  r.match_type === "none"
                    ? "border-[#DADCE0] bg-[#F1F3F4] text-[#5F6368]"
                    : "border-transparent text-[#5F6368] hover:bg-[#F1F3F4]"
                }`}
                data-testid={`match-none-${r.name}`}
              >
                Exclude
              </button>
            </div>

            <div className="col-span-3">
              <div className="flex items-center gap-3">
                <Slider
                  value={[r.weight]}
                  onValueChange={(v) => update(i, { weight: v[0] })}
                  disabled={r.match_type !== "probabilistic"}
                  min={0}
                  max={100}
                  step={1}
                  className="flex-1"
                  data-testid={`weight-slider-${r.name}`}
                />
                <Input
                  type="number"
                  min={0}
                  max={100}
                  value={r.weight}
                  onChange={(e) => update(i, { weight: Math.min(100, Math.max(0, Number(e.target.value || 0))) })}
                  disabled={r.match_type !== "probabilistic"}
                  className="w-20 text-sm border-[#DADCE0]"
                  data-testid={`weight-input-${r.name}`}
                />
                <span className="text-xs text-[#5F6368]">%</span>
              </div>
            </div>

            <div className="col-span-5">
              <Textarea
                value={r.survivorship_intent}
                onChange={(e) => update(i, { survivorship_intent: e.target.value })}
                placeholder='Example: "Pick the most frequent value; on tie, the most recent record."'
                className="h-16 text-sm border-[#DADCE0] resize-none"
                data-testid={`survivorship-textarea-${r.name}`}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Footer summary */}
      <div className="mt-5 flex items-center justify-between gap-4 reveal">
        <div className="flex items-center gap-3 text-sm">
          <Badge
            className={Math.abs(probTotal - 100) < 0.01 ? "bg-[#E6F4EA] text-[#188038] hover:bg-[#E6F4EA]" : "bg-[#FCE8E6] text-[#D93025] hover:bg-[#FCE8E6]"}
            data-testid="weight-total-badge"
          >
            Probabilistic total: {probTotal}%
          </Badge>
          <Button variant="ghost" size="sm" onClick={normalize} className="text-[#1A73E8] hover:bg-[#E8F0FE]" data-testid="normalize-weights-btn">
            <Info className="h-3.5 w-3.5 mr-1.5" />Auto-normalize
          </Button>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate("/")} className="border-[#DADCE0]" data-testid="cancel-btn">
            Cancel
          </Button>
          <Button
            onClick={onSave}
            disabled={saving}
            className="bg-[#1A73E8] hover:bg-[#1557B0] text-white"
            data-testid="save-and-continue-btn"
          >
            <Save className="h-4 w-4 mr-2" />
            {saving ? "Saving…" : "Save & Generate Strategy"}
            <ArrowRight className="h-4 w-4 ml-2" />
          </Button>
        </div>
      </div>
    </div>
  );
}
