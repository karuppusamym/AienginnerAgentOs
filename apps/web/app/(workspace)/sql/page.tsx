"use client";

import { useCallback } from "react";
import { SQLView } from "../../components/SQLView";
import { useWorkspace } from "../../lib/workspace";

export default function SQLPage() {
  const { notify, user, sqlSeed, setSqlSeed } = useWorkspace();
  const clearSeed = useCallback(() => setSqlSeed(null), [setSqlSeed]);
  return <SQLView notify={notify} seed={sqlSeed} currentUser={user} onSeedConsumed={clearSeed} />;
}
