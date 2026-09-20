/**
 * Split user-typed input into unique, trimmed values.
 *
 * Accepts spaces, commas and full-width commas as separators so users can
 * paste "报名, 紧急通知 活动通知" without worrying about the exact delimiter.
 */
export function parseList(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\s,，]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}