import { describe, expect, it } from "vitest";

import { formatTimecode, parseTimecode, pxPerUs, timecodeAt } from "./time-format.ts";

describe("formatTimecode", () => {
  it("renders seconds and frame fractions", () => {
    expect(formatTimecode(0)).toBe("00:00.000");
    expect(formatTimecode(1_000_000)).toBe("00:01.000");
    expect(formatTimecode(65_432_100)).toBe("01:05.432");
    expect(formatTimecode(3_600_000_000)).toBe("60:00.000");
  });

  it("keeps frames for the cut list", () => {
    expect(timecodeAt(1_000_000, 30)).toBe("00:00:01:00");
    expect(timecodeAt(1_033_400, 30)).toBe("00:00:01:01");
    expect(timecodeAt(0, 0)).toBe("00:00:00:00");
  });

  it("never emits a negative or fractional frame", () => {
    expect(formatTimecode(-5_000)).toBe("00:00.000");
    expect(timecodeAt(123_456.7, 25)).toBe("00:00:00:03");
  });
});

describe("parseTimecode", () => {
  it("reads back what the field accepts", () => {
    expect(parseTimecode("00:01.000")).toBe(1_000_000);
    expect(parseTimecode("1:05.432")).toBe(65_432_000);
    expect(parseTimecode("00:00:01:00", 30)).toBe(1_000_000);
    expect(parseTimecode("00:00:01:15", 30)).toBe(1_500_000);
    expect(parseTimecode("5")).toBe(5_000_000);
    expect(parseTimecode("")).toBeNull();
    expect(parseTimecode("nonsense")).toBeNull();
  });
});

describe("pxPerUs", () => {
  it("fits a timeline into the available width", () => {
    expect(pxPerUs(4_000_000, 800)).toBe(0.0002);
    expect(pxPerUs(0, 800)).toBeGreaterThan(0);
  });

  it("clamps an absurd zoom so the DOM stays finite", () => {
    expect(pxPerUs(1_000, 1_000_000_000)).toBe(1);
    expect(pxPerUs(1e12, 100)).toBeGreaterThan(0);
  });
});
