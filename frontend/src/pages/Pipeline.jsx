import { Fragment, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronRight, CloudUpload, Database, Layers, Sparkles, CheckCircle2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

const STAGES = [
  { key: "gcs_landed", label: "GCS Landing", icon: CloudUpload, desc: "File written to gs://&lt;bucket&gt;/landing/" },
  { key: "raw", label: "Raw Layer", icon: Database, desc: "Partitioned raw table created" },
  { key: "staging", label: "Staging Layer", icon: Layers, desc: "Normalized + metadata injected" },
  { key: "curated", label: "Curated Layer", icon: Sparkles, desc: "Master + Suspect tables + Search Index" },
];

export default function Pipeline() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const { data } = await api.get(`/pipeline/status/${jobId}`);
        if (!stop) setStatus(data);
      } catch (e) {/* ignore */ }
    };
    tick();
    const t = setInterval(tick, 4000);
    return () => { stop = true; clearInterval(t); };
  }, [jobId]);

  const lifecycle = status?.lifecycle || {};
  const stats = status?.stats || {};

  return (
    <div className="p-6 md:p-8 max-w-[1280px] mx-auto" data-testid="pipeline-page">
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[#5F6368] mb-1">Step 3 of 3</div>
          <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Data Lifecycle</h1>
          <p className="text-sm text-[#3C4043] mt-1 max-w-2xl">
            Four-state pipeline managed entirely within Google Cloud Platform. Hover a node
            to see its responsibilities.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate(`/sql/${jobId}`)} className="border-[#DADCE0] text-[#1A73E8] hover:bg-[#E8F0FE]" data-testid="view-sql-btn">
            View Generated SQL
          </Button>
          <Button onClick={() => navigate(`/results/${jobId}`)} className="bg-[#1A73E8] hover:bg-[#1557B0] text-white" data-testid="view-results-btn">
            View Curated Results
          </Button>
        </div>
      </div>

      {/* Pipeline Nodes */}
      <div className="bg-white border border-[#DADCE0] rounded-md p-8">
        <div className="grid grid-cols-1 md:grid-cols-7 gap-3 items-stretch">
          {STAGES.map((s, idx) => {
            const Icon = s.icon;
            const done = !!lifecycle[s.key];
            const cls = done ? "node-done" : "node-pending";
            return (
              <Fragment key={s.key}>
                <div
                  className={`md:col-span-1 col-span-1 border rounded-md p-4 ${cls} relative transition-all`}
                  data-testid={`pipeline-node-${s.key}`}
                >
                  <div className="flex items-center justify-between">
                    <Icon className="h-5 w-5" />
                    {done && <CheckCircle2 className="h-4 w-4" />}
                  </div>
                  <div className="font-display font-semibold text-sm mt-3">{s.label}</div>
                  <div className="text-[11px] mt-1 opacity-80" dangerouslySetInnerHTML={{ __html: s.desc }} />
                </div>
                {idx < STAGES.length - 1 && (
                  <div className="hidden md:flex md:col-span-1 items-center justify-center">
                    <ChevronRight className="h-6 w-6 text-[#BDC1C6]" />
                  </div>
                )}
              </Fragment>
            );
          })}
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mt-8 pt-6 border-t border-[#DADCE0]">
          <Stat label="Total Records" value={stats.total_records || 0} />
          <Stat label="Unique Masters" value={stats.unique_masters || 0} accent="green" />
          <Stat label="Duplicate Suspects" value={stats.duplicate_suspects || 0} accent="amber" />
          <Stat label="Deterministic" value={stats.deterministic_matches || 0} />
          <Stat label="Probabilistic" value={stats.probabilistic_matches || 0} />
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, accent }) {
  const color = accent === "green" ? "text-[#188038]" : accent === "amber" ? "text-[#F29900]" : "text-[#202124]";
  return (
    <div data-testid={`stat-${label.toLowerCase().replace(/\s/g,'-')}`}>
      <div className="text-[11px] uppercase tracking-[0.1em] text-[#5F6368]">{label}</div>
      <div className={`font-display text-2xl font-bold mt-1 ${color}`}>{value.toLocaleString()}</div>
    </div>
  );
}
