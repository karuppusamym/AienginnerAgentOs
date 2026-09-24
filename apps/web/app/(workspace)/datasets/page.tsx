"use client";

import { DatasetsView } from "../../components/DatasetsView";
import { useWorkspace } from "../../lib/workspace";

export default function DatasetsPage() {
  const { notify, navigate, setSqlSeed, setAnalysisSeed } = useWorkspace();
  return (
    <DatasetsView
      notify={notify}
      onOpenSQL={(dataset) => {
        setSqlSeed({ question: `Analyze ${dataset.schema_name}.${dataset.table_name} using its approved metadata`, dialect: dataset.source_name === "Local files" ? "postgres" : "sqlserver" });
        navigate("sql");
      }}
      onStartAnalysis={(dataset) => {
        setAnalysisSeed({ question: `Can you analyze the ${dataset.schema_name}.${dataset.table_name} dataset for me?`, connector_id: dataset.connector_id || "" });
        navigate("conversations", { fresh: true });
      }}
    />
  );
}
