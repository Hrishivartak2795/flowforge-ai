export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
        FlowForge AI
      </h1>

      <p className="max-w-xl text-lg text-gray-600 dark:text-gray-400">
        AI-Powered Requirements Intelligence &amp; Engineering Decision Platform
      </p>

      <div className="mt-4 flex flex-col items-center gap-1">
        <span className="text-sm uppercase tracking-widest text-gray-400">
          Current Milestone
        </span>
        <span className="rounded-full border border-gray-300 px-4 py-1 text-sm font-medium dark:border-gray-700">
          M0 Complete
        </span>
      </div>
    </main>
  );
}
