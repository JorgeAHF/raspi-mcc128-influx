import { test, expect } from "@playwright/test";

const jsonResponse = (payload: unknown) => ({
  status: 200,
  body: JSON.stringify(payload),
  headers: { "content-type": "application/json" },
});

test.describe("Edge WebUI", () => {
  test("permite editar configuración y visualizar vista previa", async ({ page }) => {
    const stationConfig = {
      station_id: "station-1",
      description: "Estación de pruebas",
      acquisition: {
        sample_rate_hz: 25,
        block_size: 10,
        duration_s: null,
        total_samples: null,
        drift_detection: { correction_threshold_ns: null },
      },
      channels: [
        {
          index: 0,
          name: "Canal 0",
          unit: "mm",
          voltage_range: 5,
          calibration: { gain: 1, offset: 0 },
        },
      ],
    };

    const storageSettings = {
      driver: "influxdb_v2",
      url: "http://localhost:8086",
      org: "demo",
      bucket: "bucket",
      token: "token",
      batch_size: 5,
      timeout_s: 5,
      queue_max_size: 1000,
      verify_ssl: true,
      retry: { max_attempts: 3, base_delay_s: 1, max_backoff_s: 30 },
      sinks: ["influxdb_v2"],
      csv: {
        enabled: true,
        directory: "/tmp",
        rotation: "session" as const,
        filename_prefix: "samples",
        timestamp_format: "%Y-%m-%dT%H:%M:%S.%fZ",
        delimiter: ",",
        decimal: ".",
        encoding: "utf-8",
        newline: "",
        write_headers: true,
      },
      ftp: {
        enabled: false,
        protocol: "ftp" as const,
        host: null,
        port: null,
        username: null,
        password: null,
        remote_dir: "/",
        local_dir: null,
        rotation: "session" as const,
        upload_interval_s: null,
        passive: true,
      },
    };

    const sessionStatus = {
      active: true,
      session: {
        mode: "continuous",
        preview: true,
        status: "running",
        started_at: new Date().toISOString(),
        finished_at: null,
        station_id: "station-1",
        error: null,
      },
    };

    let lastStationUpdate: unknown;
    let lastStorageUpdate: unknown;

    await page.addInitScript(() => {
      window.localStorage.setItem("edge-webui-token", "test-token");
    });
    page.on("dialog", (dialog) => dialog.accept());

    await page.route("**/config/mcc128", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill(jsonResponse(stationConfig));
      } else {
        lastStationUpdate = route.request().postDataJSON();
        await route.fulfill(jsonResponse(lastStationUpdate));
      }
    });

    await page.route("**/config/storage", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill(jsonResponse(storageSettings));
      } else {
        lastStorageUpdate = route.request().postDataJSON();
        await route.fulfill(jsonResponse(lastStorageUpdate));
      }
    });

    await page.route("**/acquisition/session", async (route) => {
      await route.fulfill(jsonResponse(sessionStatus));
    });

    const previewPayload = {
      station_id: "station-1",
      captured_at_ns: 1_000_000_500,
      timestamps_ns: [1_000_000_000, 1_000_000_250, 1_000_000_500],
      channels: [
        { index: 0, name: "Canal 0", unit: "mm", values: [0.1, 0.2, 0.3] },
      ],
    };

    await page.route("**/preview/stream*", async (route) => {
      await route.fulfill({
        status: 200,
        body: `data: ${JSON.stringify(previewPayload)}\n\n`,
        headers: { "content-type": "text/event-stream" },
      });
    });

    await page.goto("/");

    const stationSection = page.locator("#station");
    await expect(stationSection.locator('input[name="station_id"]')).toHaveValue("station-1");

    await stationSection.locator('input[name="description"]').fill("Actualizada");
    await stationSection.locator('input[name="block_size"]').fill("32");
    await stationSection.getByRole("button", { name: "Guardar" }).click();

    await expect.poll(() => (lastStationUpdate as any)?.acquisition?.block_size).toBe(32);

    const storageSection = page.locator("#storage");
    await expect(storageSection.locator('input[name="url"]')).toHaveValue("http://localhost:8086");
    await storageSection.locator('input[name="bucket"]').fill("nuevo-bucket");
    await storageSection.getByRole("button", { name: "Guardar" }).click();

    await expect.poll(() => (lastStorageUpdate as any)?.bucket).toBe("nuevo-bucket");

    const previewSection = page.locator("#preview");
    await previewSection.getByRole("button", { name: "Iniciar vista previa" }).click();

    await expect(async () => {
      const points = await page.evaluate(() => {
        const canvas = document.querySelector("#preview canvas") as HTMLCanvasElement | null;
        if (!canvas || !(window as any).Chart) {
          return 0;
        }
        const chart = (window as any).Chart.getChart(canvas);
        return chart?.data?.datasets?.[0]?.data?.length ?? 0;
      });
      expect(points).toBeGreaterThan(0);
    }).toPass();
  });
});
