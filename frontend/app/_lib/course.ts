import type { Course, EdCourse } from "./api";

/** Number of course hues defined in globals.css (--hue-0 … --hue-7). */
export const COURSE_HUES = 8;

/**
 * Stable hue index for a course id. A multiplicative hash spreads neighbouring
 * ids (1001, 1002, …) across the palette, and the same id always gets the same
 * colour. Ed-only courses use a separate offset so they rarely clash.
 */
export function courseHue(id: number, source: "canvas" | "ed" = "canvas"): number {
  const seed = (source === "ed" ? id + 5 : id) >>> 0;
  return (Math.imul(seed, 2654435761) >>> 0) % COURSE_HUES;
}

/** The course's code, falling back to its name. */
export function courseLabel(course: Pick<Course, "name" | "course_code">): string {
  return course.course_code?.trim() || course.name;
}

/**
 * The course's name without a leading copy of its code:
 * "CS 106B: Programming Abstractions" with code "CS 106B" -> "Programming Abstractions".
 */
export function courseTitle(course: Pick<Course, "name" | "course_code">): string {
  const code = course.course_code?.trim();
  if (code && course.name.startsWith(code)) {
    const rest = course.name.slice(code.length).replace(/^[\s:·–—-]+/, "").trim();
    if (rest) return rest;
  }
  return course.name;
}

export function edCourseLabel(course: Pick<EdCourse, "code" | "name">): string {
  return course.code?.trim() || course.name;
}
