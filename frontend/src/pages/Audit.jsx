import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowUpRight, ScrollText } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

export default function Audit() {
  const [jobs, setJobs] = useState([]);
  const [kpis, setKpis] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      const [{ data: a }, { data: k }] = await Promise.all([
        api.get("/audit"),
        api.get("/dashboard/kpis"),
      ]);
      setJobs(a.jobs || []);
      setKpis(k);
    })();
  }, []);

  return (
    <div className="p-6 md:p-8 max-w-[1280px] mx-auto" data-testid="audit-page">
      <div className="mb-6">
        <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Audit Trail</h1>
        <p className="text-sm text-[#3C4043] mt-1">
          Every run is recorded. <code className="mono text-xs">user_intent_store.json</code> is updated before each pipeline so re-runs are deterministic.
        </p>
      </div>

      {kpis && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          <Kpi label="Total Jobs" value={kpis.total_jobs} />
          <Kpi label="Curated" value={kpis.curated_jobs} accent="green" />
          <Kpi label="Records Ingested" value={kpis.records_ingested} />
          <Kpi label="Golden Records" value={kpis.golden_records} accent="green" />
          <Kpi label="Duplicates Found" value={kpis.duplicates_found} accent="amber" />
        </div>
      )}

      <div className="bg-white border border-[#DADCE0] rounded-md overflow-hidden">
        <table className="w-full table-dense" data-testid="audit-table">
          <thead>
            <tr>
              <th className="text-left">Job ID</th>
              <th className="text-left">File</th>
              <th className="text-left">Rows</th>
              <th className="text-left">State</th>
              <th className="text-left">Created</th>
              <th className="text-right">Re-run</th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && (
              <tr><td colSpan={6} className="text-center text-[#5F6368] py-8">No jobs yet — upload a file to begin.</td></tr>
            )}
            {jobs.map((j) => (
              <tr key={j.job_id} className="border-t border-[#DADCE0] hover:bg-[#F8F9FA]" data-testid={`audit-row-${j.job_id}`}>
                <td className="mono text-xs">{j.job_id}</td>
                <td className="text-sm">{j.filename}</td>
                <td className="text-sm">{(j.row_count || 0).toLocaleString()}</td>
                <td><StateBadge state={j.state} /></td>
                <td className="text-xs text-[#5F6368]">{j.created_at?.slice(0,19).replace("T"," ")}</td>
                <td className="text-right">
                  <button
                    onClick={() => navigate(j.intent ? `/strategy/${j.job_id}` : `/configure/${j.job_id}`)}
                    className="inline-flex items-center text-[#1A73E8] hover:underline text-xs"
                    data-testid={`audit-open-${j.job_id}`}
                  >
                    Open <ArrowUpRight className="h-3 w-3 ml-1" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Kpi({ label, value, accent }) {
  const color = accent === "green" ? "text-[#188038]" : accent === "amber" ? "text-[#F29900]" : "text-[#202124]";
  return (
    <div className="bg-white border border-[#DADCE0] rounded-md p-4" data-testid={`kpi-${label.toLowerCase().replace(/\s/g,'-')}`}>
      <div className="text-[11px] uppercase tracking-[0.1em] text-[#5F6368] flex items-center gap-1.5"><ScrollText className="h-3 w-3"/>{label}</div>
      <div className={`font-display text-2xl font-bold mt-1 ${color}`}>{Number(value || 0).toLocaleString()}</div>
    </div>
  );
}

function StateBadge({ state }) {
  const map = {
    gcs_landed: "bg-[#F1F3F4] text-[#5F6368]",
    intent_saved: "bg-[#E8F0FE] text-[#1A73E8]",
    curated: "bg-[#E6F4EA] text-[#188038]",
  };
  return <Badge className={`${map[state] || ""} hover:opacity-100`}>{state || "—"}</Badge>;
}
