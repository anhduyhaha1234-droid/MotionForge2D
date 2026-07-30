"use client";

import { useProjectStore } from "@/stores/project";
import { ScreenA } from "@/components/ScreenA";
import { ScreenB } from "@/components/ScreenB";
import { ScreenC } from "@/components/ScreenC";
import { ScreenD } from "@/components/ScreenD";
import { ScreenE } from "@/components/ScreenE";

export default function Home() {
  const screen = useProjectStore((s) => s.screen);

  switch (screen) {
    case "start":
      return <ScreenA />;
    case "selection":
      return <ScreenB />;
    case "review":
      return <ScreenC />;
    case "replacement":
      return <ScreenD />;
    case "render":
      return <ScreenE />;
    default:
      return <ScreenA />;
  }
}
