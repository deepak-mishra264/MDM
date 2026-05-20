import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowRight, Save, Info, Plus, X, Check, ChevronsUpDown,
  ArrowUpDown, KeyRound, Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from "@/components/ui/command";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export default function Configure() {
  const { jobId } = useParams();
  const navigate = useNavigate();

  const [job, setJob] = useState(null);
  const [detCols, setDetCols] = useState([]);          // string[]
  const [probCols, setProbCols] = useState([]);        // {name, weight}[]
  const [rules, setRules] = useState([]);              // {column, rule, precedence}[]
  const [detPicker, setDetPicker] = useState(false);
  const [probPicker, setProbPicker] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const { data } = await api.get(`/jobs/${jobId}`);
        if (!active) return;
        setJob(data);
        try {
          const { data: intent } = await api.get(`/intent/${jobId}`);
          setDetCols(intent.deterministic_columns || []);
          setProbCols(intent.probabilistic_columns || []);
          setRules(intent.survivorship_rules || []);
        } catch {
          // First-time defaults
          const cols = data.columns || [];
          // Key attribute = obvious unique-ish identifier (email by default)
          const detDefault = cols.filter((c) => /^email$/i.test(c)).slice(0, 1);
          // Probabilistic = name + phone-like fields, skip pure ID columns
          const probDefault = cols
            .filter((c) => /name|phone|mobile/i.test(c) && !/^id$|_id$/i.test(c))
            .slice(0, 4);
          setDetCols(detDefault);
          if (probDefault.length) {
            const base = Math.floor(100 / probDefault.length);
            let rem = 100 - base * probDefault.length;
            setProbCols(
              probDefault.map((n) => {
                const extra = rem > 0 ? 1 : 0;
                rem -= extra;
                return { name: n, weight: base + extra };
              })
            );
          }
        }
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Job not found");
        navigate("/");
      }
    })();
    return () => { active = false; };
  }, [jobId, navigate]);

  const probTotal = useMemo(
    () => probCols.reduce((s, c) => s + Number(c.weight || 0), 0),
    [probCols]
  );

  // -- Deterministic toggle/remove --
  const toggleDet = (name) => {
    setDetCols((cur) => (cur.includes(name) ? cur.filter((x) => x !== name) : [...cur, name]));
  };
  const removeDet = (name) => setDetCols((cur) => cur.filter((x) => x !== name));

  // -- Probabilistic toggle/update/remove --
  const toggleProb = (name) => {
    setProbCols((cur) => {
      const exists = cur.find((c) => c.name === name);
      if (exists) return cur.filter((c) => c.name !== name);
      return [...cur, { name, weight: 0 }];
    });
  };
  const updateProbWeight = (name, weight) => {
    setProbCols((cur) => cur.map((c) => (c.name === name ? { ...c, weight } : c)));
  };
  const removeProb = (name) => setProbCols((cur) => cur.filter((c) => c.name !== name));

  const normalize = () => {
    if (!probCols.length) return;
    const base = Math.floor(100 / probCols.length);
    let rem = 100 - base * probCols.length;
    setProbCols((cur) =>
      cur.map((c) => {
        const extra = rem > 0 ? 1 : 0;
        rem -= extra;
        return { ...c, weight: base + extra };
      })
    );
    toast.success("Weights normalized to 100%");
  };

  // -- Survivorship rules --
  const addRule = () => {
    const cols = job?.columns || [];
    if (!cols.length) return;
    const nextPrec = (rules.length ? Math.max(...rules.map((r) => r.precedence || 0)) : 0) + 1;
    setRules((cur) => [
      ...cur,
      { column: cols[0], rule: "", precedence: nextPrec },
    ]);
  };
  const updateRule = (idx, patch) =>
    setRules((cur) => cur.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  const removeRule = (idx) => setRules((cur) => cur.filter((_, i) => i !== idx));

  const sortedRules = useMemo(
    () =>
      rules
        .map((r, originalIdx) => ({ ...r, originalIdx }))
        .sort((a, b) => (a.precedence || 999) - (b.precedence || 999)),
    [rules]
  );

  const onSave = async () => {
    if (detCols.length === 0 && probCols.length === 0) {
      toast.error("Pick at least one Key Attribute or Suspect-Score Attribute.");
      return;
    }
    if (probCols.length > 0 && Math.abs(probTotal - 100) > 0.01) {
      toast.error(`Suspect-Score weights must total 100 (currently ${probTotal}).`);
      return;
    }
    setSaving(true);
    try {
      await api.post("/intent/save", {
        job_id: jobId,
        threshold: 0.75,
        deterministic_columns: detCols,
        probabilistic_columns: probCols,
        survivorship_rules: rules.filter((r) => r.column),
      });
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
  const availableColumns = job.columns || [];

  return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto" data-testid="configure-page">
      {/* Header */}
      <div className="flex items-start justify-between gap-6 mb-6">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[#5F6368] mb-1">Step 1 of 3</div>
          <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Configure Matching</h1>
          <p className="text-sm text-[#3C4043] mt-1 max-w-2xl">
            Define <strong>Key Attributes</strong> for exact-match (deterministic) and
            <strong> Suspect-Score Attributes</strong> for weighted fuzzy matching. They can
            overlap or be completely different sets.
          </p>
        </div>
        <div className="text-right text-xs text-[#5F6368] shrink-0">
          <div>File · <span className="mono text-[#202124]">{job.filename}</span></div>
          <div>Rows · {job.row_count?.toLocaleString()} · Columns · {availableColumns.length}</div>
        </div>
      </div>

      {/* SECTION A — Key Attributes (Deterministic) */}
      <SectionCard
        icon={<KeyRound className="h-4 w-4 text-[#188038]" />}
        title="Key Attributes · Deterministic"
        subtitle="All selected columns must match exactly for two records to merge. No weighting needed."
        testId="det-section"
        picker={
          <ColumnPicker
            open={detPicker}
            onOpenChange={setDetPicker}
            columns={availableColumns}
            sample={job.sample?.[0]}
            isChecked={(c) => detCols.includes(c)}
            onToggle={toggleDet}
            triggerTestId="open-det-picker"
            itemTestIdPrefix="det-picker"
            buttonLabel="Add / Remove Key Attributes"
            accent="green"
          />
        }
      >
        {detCols.length === 0 ? (
          <EmptyHint
            label="No Key Attributes selected — clusters will rely purely on the Suspect Score."
            ctaLabel="Pick Key Attributes"
            onClick={() => setDetPicker(true)}
            testId="no-det-cols"
            ctaTestId="empty-add-det"
            accent="green"
          />
        ) : (
          <div className="flex flex-wrap gap-2" data-testid="det-chips">
            {detCols.map((c) => (
              <span
                key={c}
                className="inline-flex items-center gap-2 pl-3 pr-1 py-1 rounded-full bg-[#E6F4EA] text-[#0E5E2B] text-sm border border-[#CEEAD6]"
                data-testid={`det-chip-${c}`}
              >
                <span className="mono">{c}</span>
                <button
                  className="h-5 w-5 rounded-full hover:bg-[#CEEAD6] flex items-center justify-center"
                  onClick={() => removeDet(c)}
                  data-testid={`det-remove-${c}`}
                  aria-label={`Remove ${c}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}
      </SectionCard>

      {/* SECTION B — Probabilistic / Suspect Score */}
      <SectionCard
        icon={<Sparkles className="h-4 w-4 text-[#1A73E8]" />}
        title="Suspect-Score Attributes · Probabilistic"
        subtitle="Weighted fuzzy match. Weights drive the Suspect Score. Total must equal 100%."
        testId="prob-section"
        className="mt-5"
        picker={
          <ColumnPicker
            open={probPicker}
            onOpenChange={setProbPicker}
            columns={availableColumns}
            sample={job.sample?.[0]}
            isChecked={(c) => !!probCols.find((p) => p.name === c)}
            onToggle={toggleProb}
            triggerTestId="open-prob-picker"
            itemTestIdPrefix="prob-picker"
            buttonLabel="Add / Remove Suspect-Score Attributes"
            accent="blue"
          />
        }
      >
        {probCols.length === 0 ? (
          <EmptyHint
            label="No Suspect-Score Attributes selected — clusters will rely purely on Key Attributes."
            ctaLabel="Pick Suspect-Score Attributes"
            onClick={() => setProbPicker(true)}
            testId="no-prob-cols"
            ctaTestId="empty-add-prob"
            accent="blue"
          />
        ) : (
          <div className="space-y-2.5">
            {probCols.map((c) => (
              <div
                key={c.name}
                className="grid grid-cols-12 gap-3 items-center px-3 py-2.5 border border-[#DADCE0] rounded-md hover:bg-[#F8F9FA]"
                data-testid={`prob-row-${c.name}`}
              >
                <div className="col-span-3">
                  <Badge className="bg-[#E8F0FE] text-[#1A73E8] hover:bg-[#E8F0FE] mono">{c.name}</Badge>
                </div>
                <div className="col-span-7 flex items-center gap-3">
                  <Slider
                    value={[c.weight]}
                    onValueChange={(v) => updateProbWeight(c.name, v[0])}
                    min={0} max={100} step={1}
                    className="flex-1"
                    data-testid={`weight-slider-${c.name}`}
                  />
                  <Input
                    type="number"
                    min={0} max={100}
                    value={c.weight}
                    onChange={(e) =>
                      updateProbWeight(c.name, Math.min(100, Math.max(0, Number(e.target.value || 0))))
                    }
                    className="w-20 text-sm border-[#DADCE0]"
                    data-testid={`weight-input-${c.name}`}
                  />
                  <span className="text-xs text-[#5F6368]">%</span>
                </div>
                <div className="col-span-2 flex justify-end">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => removeProb(c.name)}
                    className="text-[#5F6368] hover:text-[#D93025] hover:bg-[#FCE8E6]"
                    data-testid={`remove-prob-${c.name}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
            <div className="flex items-center justify-between pt-2">
              <div className="flex items-center gap-3">
                <Badge
                  className={
                    Math.abs(probTotal - 100) < 0.01
                      ? "bg-[#E6F4EA] text-[#188038] hover:bg-[#E6F4EA]"
                      : "bg-[#FCE8E6] text-[#D93025] hover:bg-[#FCE8E6]"
                  }
                  data-testid="weight-total-badge"
                >
                  Total: {probTotal}%
                </Badge>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={normalize}
                  className="text-[#1A73E8] hover:bg-[#E8F0FE]"
                  data-testid="normalize-btn"
                >
                  <Info className="h-3.5 w-3.5 mr-1.5" />Auto-normalize
                </Button>
              </div>
              <div className="text-xs text-[#5F6368]">
                Suspect-Score threshold: <strong className="text-[#202124]">75%</strong>
              </div>
            </div>
          </div>
        )}
      </SectionCard>

      {/* SECTION C — Survivorship Rules */}
      <SectionCard
        icon={<ArrowUpDown className="h-4 w-4 text-[#5F6368]" />}
        title="Survivorship Rules"
        subtitle="Define golden-record logic per column. Lower precedence number wins when multiple rules target the same column."
        testId="survivorship-section"
        className="mt-5"
        picker={
          <Button
            variant="outline"
            size="sm"
            className="border-[#DADCE0] text-[#1A73E8] hover:bg-[#E8F0FE]"
            onClick={addRule}
            data-testid="add-rule-btn"
          >
            <Plus className="h-3.5 w-3.5 mr-1.5" />Add rule
          </Button>
        }
      >
        {sortedRules.length === 0 ? (
          <div className="border border-dashed border-[#DADCE0] rounded-md p-6 text-center" data-testid="no-rules">
            <div className="text-sm text-[#5F6368]">
              No survivorship rules yet. Default: most-recent non-null per column.
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-12 gap-3 px-3 text-[11px] uppercase tracking-[0.06em] text-[#5F6368]">
              <div className="col-span-1 flex items-center gap-1">
                <ArrowUpDown className="h-3 w-3" />Prec
              </div>
              <div className="col-span-3">Column</div>
              <div className="col-span-7">Rule (Plain English)</div>
              <div className="col-span-1"></div>
            </div>
            {sortedRules.map((r) => (
              <div
                key={`${r.originalIdx}-${r.column}`}
                className="grid grid-cols-12 gap-3 items-start px-3 py-2 border border-[#DADCE0] rounded-md"
                data-testid={`rule-row-${r.originalIdx}`}
              >
                <div className="col-span-1">
                  <Input
                    type="number"
                    min={1}
                    value={r.precedence}
                    onChange={(e) => updateRule(r.originalIdx, { precedence: Number(e.target.value || 1) })}
                    className="w-full text-sm border-[#DADCE0]"
                    data-testid={`rule-precedence-${r.originalIdx}`}
                  />
                </div>
                <div className="col-span-3">
                  <Select value={r.column} onValueChange={(v) => updateRule(r.originalIdx, { column: v })}>
                    <SelectTrigger className="border-[#DADCE0] text-sm" data-testid={`rule-column-${r.originalIdx}`}>
                      <SelectValue placeholder="Pick column" />
                    </SelectTrigger>
                    <SelectContent>
                      {availableColumns.map((c) => (
                        <SelectItem key={c} value={c}>{c}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="col-span-7">
                  <Textarea
                    value={r.rule}
                    onChange={(e) => updateRule(r.originalIdx, { rule: e.target.value })}
                    placeholder='Example: "Pick the most frequent value; on tie, the most recent record."'
                    className="h-14 text-sm border-[#DADCE0] resize-none"
                    data-testid={`rule-text-${r.originalIdx}`}
                  />
                </div>
                <div className="col-span-1 flex justify-end pt-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => removeRule(r.originalIdx)}
                    className="text-[#5F6368] hover:text-[#D93025] hover:bg-[#FCE8E6]"
                    data-testid={`remove-rule-${r.originalIdx}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* Footer */}
      <div className="mt-6 flex items-center justify-between gap-4">
        <div className="text-xs text-[#5F6368]">
          {detCols.length} key attribute(s) · {probCols.length} suspect-score attribute(s) ·
          {" "}{rules.length} survivorship rule(s) · threshold 75%
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

// --- Helpers ----

function SectionCard({ icon, title, subtitle, picker, children, testId, className = "" }) {
  return (
    <section className={`bg-white border border-[#DADCE0] rounded-md p-5 ${className}`} data-testid={testId}>
      <div className="flex items-center justify-between mb-3 gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {icon}
            <div className="font-display font-semibold text-[15px]">{title}</div>
          </div>
          <div className="text-xs text-[#5F6368] mt-0.5">{subtitle}</div>
        </div>
        {picker}
      </div>
      {children}
    </section>
  );
}

function ColumnPicker({
  open, onOpenChange, columns, sample, isChecked, onToggle,
  triggerTestId, itemTestIdPrefix, buttonLabel, accent,
}) {
  const colorClass =
    accent === "green"
      ? "text-[#188038] hover:bg-[#E6F4EA] border-[#CEEAD6]"
      : "text-[#1A73E8] hover:bg-[#E8F0FE] border-[#DADCE0]";
  const checkedClass = accent === "green" ? "bg-[#188038] border-[#188038]" : "bg-[#1A73E8] border-[#1A73E8]";
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className={`border ${colorClass}`} data-testid={triggerTestId}>
          <Plus className="h-3.5 w-3.5 mr-1.5" />{buttonLabel}
          <ChevronsUpDown className="h-3.5 w-3.5 ml-1.5 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[340px] p-0 bg-white border-[#DADCE0]" align="end">
        <Command>
          <CommandInput placeholder="Search columns…" />
          <CommandList>
            <CommandEmpty>No columns found.</CommandEmpty>
            <CommandGroup>
              {columns.map((c) => {
                const checked = isChecked(c);
                return (
                  <CommandItem
                    key={c}
                    onSelect={() => onToggle(c)}
                    className="cursor-pointer"
                    data-testid={`${itemTestIdPrefix}-item-${c}`}
                  >
                    <div
                      className={`mr-2 h-4 w-4 rounded border flex items-center justify-center ${
                        checked ? checkedClass : "border-[#DADCE0]"
                      }`}
                    >
                      {checked && <Check className="h-3 w-3 text-white" />}
                    </div>
                    <span className="text-sm">{c}</span>
                    <span className="text-[11px] mono text-[#5F6368] ml-auto truncate max-w-[110px]">
                      {sample?.[c] || ""}
                    </span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function EmptyHint({ label, ctaLabel, onClick, testId, ctaTestId, accent }) {
  const color = accent === "green" ? "text-[#188038] hover:bg-[#E6F4EA]" : "text-[#1A73E8] hover:bg-[#E8F0FE]";
  return (
    <div className="border border-dashed border-[#DADCE0] rounded-md p-6 text-center" data-testid={testId}>
      <div className="text-sm text-[#5F6368]">{label}</div>
      <Button variant="ghost" size="sm" className={`mt-2 ${color}`} onClick={onClick} data-testid={ctaTestId}>
        <Plus className="h-3.5 w-3.5 mr-1.5" />{ctaLabel}
      </Button>
    </div>
  );
}
