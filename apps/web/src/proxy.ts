import { clerkMiddleware } from "@clerk/nextjs/server";

export default clerkMiddleware(async (auth, request) => {
  // Resolve authentication before streaming the workspace shell. Pages retain
  // their own checks, but an invalid session must not become a blank page body.
  const path = request.nextUrl.pathname;
  // API handlers retain their JSON authentication responses; sign-in and
  // health routes must remain reachable while a session is recovering.
  const publicRoute =
    path === "/health" ||
    ["/sign-in", "/sign-up", "/api"].some(
      (prefix) => path === prefix || path.startsWith(`${prefix}/`),
    );
  if (!publicRoute) await auth.protect();
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
