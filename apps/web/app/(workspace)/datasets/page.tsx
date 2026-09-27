"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { DatasetsView } from "../../components/DatasetsView";
import { LoadingBlock } from "../../components/shared";
import { useWorkspace } from "../../lib/workspace";

export default function DatasetsPage() {
  return (
    <Suspense fallback={<LoadingBlock label="Opening datasets" />}>
      <DatasetsRoute />
    </Suspense>
  );
}

/** `?asset=<id>` preselects a dataset (deep links from the relationship explorer). */
function DatasetsRoute() {
  const { notify, navigate, setSqlSeed, setAnalysisSeed } = useWorkspace();
  const assetId = useSearchParams()?.get("asset") || null;
  return (
    <DatasetsView
      notify={notify}
      initialAssetId={assetId}
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
