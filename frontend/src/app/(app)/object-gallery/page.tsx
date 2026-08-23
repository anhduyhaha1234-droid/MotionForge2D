"use client";

/**
 * Object Gallery route (S08-T04) — /object-gallery?project=<id>[&video=<id>]
 *
 * Thin route wrapper: reads the project id (and optional explicit video
 * item id for multi-video projects) from the query string inside a
 * Suspense boundary and delegates to the gallery panel.
 */

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ObjectGalleryPanel } from "@/components/object-gallery/ObjectGalleryPanel";

export default function ObjectGalleryPage() {
  return (
    <Suspense fallback={<div className="min-h-full p-4 sm:p-6" aria-busy="true" />}>
      <ObjectGalleryRoute />
    </Suspense>
  );
}

function ObjectGalleryRoute() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const projectId = searchParams.get("project");
  const videoParam = searchParams.get("video");
  return (
    <div className="min-h-full p-4 sm:p-6">
      <ObjectGalleryPanel
        projectId={projectId}
        videoParam={videoParam}
        onVideoChange={(videoItemId) => {
          if (projectId) {
            router.replace(
              `/object-gallery?project=${encodeURIComponent(projectId)}&video=${encodeURIComponent(videoItemId)}`,
            );
          }
        }}
      />
    </div>
  );
}
