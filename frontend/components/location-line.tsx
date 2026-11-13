"use client";

import type { FC } from "react";
import { MapPinIcon, TriangleAlertIcon } from "lucide-react";

import { useT } from "@/lib/i18n";
import type { SensorLocation } from "@/lib/packet";

/** Coordinates as plain decimals with a dot in every language, so they can be copied into a map. */
const coordinate = (value: number) => String(Number(value.toFixed(5)));

/**
 * "Location: <site> (<lat>, <lon>) · from site profile", with a warning when a signal sits on GPS.
 * The location always comes from the site profile, never from the browser's geolocation.
 */
export const LocationLine: FC<{ location: SensorLocation; gpsInterference: boolean }> = ({
  location,
  gpsInterference,
}) => {
  const { t } = useT();
  const hasCoords = typeof location.latitude === "number" && typeof location.longitude === "number";

  return (
    <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <span className="flex items-center gap-1.5">
        <MapPinIcon aria-hidden className="size-3.5 shrink-0" />
        {hasCoords
          ? t("location.at", {
              site: location.name,
              lat: coordinate(location.latitude as number),
              lon: coordinate(location.longitude as number),
            })
          : t("location.atNoCoords", { site: location.name })}
      </span>
      {gpsInterference && (
        <span role="note" className="flex items-center gap-1.5 text-amber-300">
          <TriangleAlertIcon aria-hidden className="size-3.5 shrink-0" />
          {t("location.gpsWarning")}
        </span>
      )}
    </div>
  );
};
