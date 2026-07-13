"use client";

import dynamic from "next/dynamic";

// MapLibre needs `window`, so load the app only on the client.
const BuildableApp = dynamic(() => import("@/components/BuildableApp"), {
  ssr: false,
  loading: () => (
    <div className="flex h-screen w-full items-center justify-center text-sm text-zinc-500">
      Loading map…
    </div>
  ),
});

export default function Home() {
  return <BuildableApp />;
}
