import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowRight, Save, Info, Plus, X, Check, ChevronsUpDown, ArrowUpDown } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function Configure() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [matchCols, setMatchCols] = useState([]); // [{name, weight}]
  const [rules, setRules] = useState([]); // [{column, rule, precedence}]
  const [picker, setPicker] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const { data } = await api.get(`/jobs/${jobId}`);
        if (!active) return;
        setJob(data);
        // Try to load any previous intent
        try {
          const { data: intent } = await api.get(`/intent/${jobId}`);
          setMatchCols(intent.match_columns || []);
          setRules(intent.survivorship_rules || []);
        } catch {
          // first-time defaults: pre-pick obvious ID-like columns
          const cols = data.columns || [];
          const preferred = cols.filter((c) => /name|email|phone|mobile|id$/i.test(c)).slice(0, 4);
          if (preferred.length > 0) {
            const base = Math.floor(100 / preferred.length);
            let rem = 100 - base * preferred.length;
            setMatchCols(
              preferred.map((c) => {
                const extra = rem > 0 ? 1 : 0;
                rem -= extra;
                return { name: c, weight: base + extra };
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

  const totalWeight = useMemo(
    () => matchCols.reduce((s, c) => s + Number(c.weight || 0), 0),
    [matchCols]
  );

  const toggleColumn = (name) => {
    setMatchCols((cur) => {
      const exists = cur.find((c) => c.name === name);
      if (exists) return cur.filter((c) => c.name !== name);
      return [...cur, { name, weight: 0 }];
    });
  };

  const updateWeight = (name, weight) => {
    setMatchCols((cur) => cur.map((c) => (c.name === name ? { ...c, weight } : c)));
  };

  const removeColumn = (name) => {
    setMatchCols((cur) => cur.filter((c) => c.name !== name));
    setRules((cur) => cur.filter((r) => r.column !== name));
  };

  const normalize = () => {
    if (!matchCols.length) return;
    const base = Math.floor(100 / matchCols.length);
    let rem = 100 - base * matchCols.length;
    setMatchCols((cur) =>
      cur.map((c) => {
        const extra = rem > 0 ? 1 : 0;
        rem -= extra;
        return { ...c, weight: base + extra };
      })
    );
    toast.success("Weights normalized to 100%");
  };

  const addRule = () => {
    if (!matchCols.length && !(job?.columns || []).length) return;
    const nextPrec = (rules.length ? Math.max(...rules.map((r) => r.precedence || 0)) : 0) + 1;
    setRules((cur) => [
      ...cur,
      { column: job?.columns?.[0] || "", rule: "", precedence: nextPrec },
    ]);
  };

  const updateRule = (idx, patch) => {
    setRules((cur) => cur.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const removeRule = (idx) => {
    setRules((cur) => cur.filter((_, i) => i !== idx));
  };

  const sortedRules = useMemo(
    () => [...rules].sort((a, b) => (a.precedence || 999) - (b.precedence || 999)),
    [rules]
  );

  const onSave = async () => {
    if (matchCols.length === 0) {
      toast.error("Select at least one column for matching.");
      return;
    }
    if (Math.abs(totalWeight - 100) > 0.01) {
      toast.error(`Weights must total 100 (currently ${totalWeight}).`);
      return;
    }
    setSaving(true);
    try {
      await api.post("/intent/save", {
        job_id: jobId,
        threshold: 0.75,
        match_columns: matchCols,
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
      <div className="flex items-start justify-between gap-6 mb-6">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[#5F6368] mb-1">Step 1 of 3</div>
          <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Configure Matching</h1>
          <p className="text-sm text-[#3C4043] mt-1 max-w-2xl">
            Pick the columns the agent should use for matching. Selected columns drive
            <strong> both</strong> the deterministic (all-exact) and probabilistic
            (weighted fuzzy) engines.
          </p>
        </div>
        <div className="text-right text-xs text-[#5F6368] shrink-0">
          <div>File · <span className="mono text-[#202124]">{job.filename}</span></div>
          <div>Rows · {job.row_count?.toLocaleString()} · Columns · {availableColumns.length}</div>
        </div>
      </div>

      {/* SECTION A — Match columns */}
      <section className="bg-white border border-[#DADCE0] rounded-md p-5" data-testid="match-columns-section">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="font-display font-semibold text-[15px]">Match Columns</div>
            <div className="text-xs text-[#5F6368]">Used by both engines. Weights drive the probabilistic score.</div>
          </div>
          <Popover open={picker} onOpenChange={setPicker}>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="border-[#DADCE0] text-[#1A73E8] hover:bg-[#E8F0FE]" data-testid="open-column-picker">
                <Plus className="h-3.5 w-3.5 mr-1.5" />Add / Remove columns
                <ChevronsUpDown className="h-3.5 w-3.5 ml-1.5 opacity-60" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-[320px] p-0 bg-white border-[#DADCE0]" align="end">
              <Command>
                <CommandInput placeholder="Search columns…" />
                <CommandList>
                  <CommandEmpty>No columns found.</CommandEmpty>
                  <CommandGroup>
                    {availableColumns.map((c) => {
                      const checked = !!matchCols.find((mc) => mc.name === c);
                      return (
                        <CommandItem
                          key={c}
                          onSelect={() => toggleColumn(c)}
                          className="cursor-pointer"
                          data-testid={`picker-item-${c}`}
                        >
                          <div className={`mr-2 h-4 w-4 rounded border flex items-center justify-center ${checked ? "bg-[#1A73E8] border-[#1A73E8]" : "border-[#DADCE0]"}`}>
                            {checked && <Check className="h-3 w-3 text-white" />}
                          </div>
                          <span className="text-sm">{c}</span>
                          <span className="text-[11px] mono text-[#5F6368] ml-auto truncate max-w-[100px]">
                            {job.sample?.[0]?.[c] || ""}
                          </span>
                        </CommandItem>
                      );
                    })}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        </div>

        {matchCols.length === 0 ? (
          <div className="border border-dashed border-[#DADCE0] rounded-md p-8 text-center" data-testid="no-match-columns">
            <div className="text-sm text-[#5F6368]">No columns selected yet.</div>
            <Button variant="ghost" size="sm" className="mt-2 text-[#1A73E8] hover:bg-[#E8F0FE]" onClick={() => setPicker(true)} data-testid="empty-add-column-btn">
              <Plus className="h-3.5 w-3.5 mr-1.5" />Pick columns
            </Button>
          </div>
        ) : (
          <div className="space-y-2.5">
            {matchCols.map((c) => (
              <div
                key={c.name}
                className="grid grid-cols-12 gap-3 items-center px-3 py-2.5 border border-[#DADCE0] rounded-md hover:bg-[#F8F9FA]"
                data-testid={`match-row-${c.name}`}
              >
                <div className="col-span-3">
                  <Badge className="bg-[#E8F0FE] text-[#1A73E8] hover:bg-[#E8F0FE] mono">{c.name}</Badge>
                </div>
                <div className="col-span-7 flex items-center gap-3">
                  <Slider
                    value={[c.weight]}
                    onValueChange={(v) => updateWeight(c.name, v[0])}
                    min={0} max={100} step={1}
                    className="flex-1"
                    data-testid={`weight-slider-${c.name}`}
                  />
                  <Input
                    type="number"
                    min={0} max={100}
                    value={c.weight}
                    onChange={(e) => updateWeight(c.name, Math.min(100, Math.max(0, Number(e.target.value || 0))))}
                    className="w-20 text-sm border-[#DADCE0]"
                    data-testid={`weight-input-${c.name}`}
                  />
                  <span className="text-xs text-[#5F6368]">%</span>
                </div>
                <div className="col-span-2 flex justify-end">
                  <Button variant="ghost" size="sm" onClick={() => removeColumn(c.name)} className="text-[#5F6368] hover:text-[#D93025] hover:bg-[#FCE8E6]" data-testid={`remove-column-${c.name}`}>
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
            <div className="flex items-center justify-between pt-2">
              <div className="flex items-center gap-3">
                <Badge
                  className={Math.abs(totalWeight - 100) < 0.01 ? "bg-[#E6F4EA] text-[#188038] hover:bg-[#E6F4EA]" : "bg-[#FCE8E6] text-[#D93025] hover:bg-[#FCE8E6]"}
                  data-testid="weight-total-badge"
                >
                  Total: {totalWeight}%
                </Badge>
                <Button variant="ghost" size="sm" onClick={normalize} className="text-[#1A73E8] hover:bg-[#E8F0FE]" data-testid="normalize-btn">
                  <Info className="h-3.5 w-3.5 mr-1.5" />Auto-normalize
                </Button>
              </div>
              <div className="text-xs text-[#5F6368]">
                Threshold for cluster merge: <strong className="text-[#202124]">75%</strong>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* SECTION B — Survivorship Rules */}
      <section className="bg-white border border-[#DADCE0] rounded-md p-5 mt-5" data-testid="survivorship-section">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="font-display font-semibold text-[15px]">Survivorship Rules</div>
            <div className="text-xs text-[#5F6368]">
              Define golden-record logic per column. Lower precedence number wins when multiple rules target the same column.
            </div>
          </div>
          <Button variant="outline" size="sm" className="border-[#DADCE0] text-[#1A73E8] hover:bg-[#E8F0FE]" onClick={addRule} data-testid="add-rule-btn">
            <Plus className="h-3.5 w-3.5 mr-1.5" />Add rule
          </Button>
        </div>

        {sortedRules.length === 0 ? (
          <div className="border border-dashed border-[#DADCE0] rounded-md p-6 text-center" data-testid="no-rules">
            <div className="text-sm text-[#5F6368]">No survivorship rules yet. Default: most-recent non-null per column.</div>
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
            {sortedRules.map((r) => {
              // map back to original index for state updates
              const idx = rules.findIndex((x) => x === r);
              return (
                <div
                  key={`${r.column}-${r.precedence}-${idx}`}
                  className="grid grid-cols-12 gap-3 items-start px-3 py-2 border border-[#DADCE0] rounded-md"
                  data-testid={`rule-row-${idx}`}
                >
                  <div className="col-span-1">
                    <Input
                      type="number"
                      min={1}
                      value={r.precedence}
                      onChange={(e) => updateRule(idx, { precedence: Number(e.target.value || 1) })}
                      className="w-full text-sm border-[#DADCE0]"
                      data-testid={`rule-precedence-${idx}`}
                    />
                  </div>
                  <div className="col-span-3">
                    <Select value={r.column} onValueChange={(v) => updateRule(idx, { column: v })}>
                      <SelectTrigger className="border-[#DADCE0] text-sm" data-testid={`rule-column-${idx}`}>
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
                      onChange={(e) => updateRule(idx, { rule: e.target.value })}
                      placeholder='Example: "Pick the most frequent value; on tie, the most recent record."'
                      className="h-14 text-sm border-[#DADCE0] resize-none"
                      data-testid={`rule-text-${idx}`}
                    />
                  </div>
                  <div className="col-span-1 flex justify-end pt-1">
                    <Button variant="ghost" size="sm" onClick={() => removeRule(idx)} className="text-[#5F6368] hover:text-[#D93025] hover:bg-[#FCE8E6]" data-testid={`remove-rule-${idx}`}>
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Footer */}
      <div className="mt-6 flex items-center justify-between gap-4">
        <div className="text-xs text-[#5F6368]">
          {matchCols.length} match column(s) · {rules.length} survivorship rule(s) · threshold 75%
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
