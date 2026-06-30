import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-xl flex-col items-center justify-center px-4 text-center">
      <h1 className="text-3xl font-semibold text-white">Page not found</h1>
      <p className="mt-3 text-sm text-gray-400">
        The workspace page you opened is not available.
      </p>
      <Link
        href="/bulk"
        className="mt-6 rounded bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
      >
        Open bulk editor
      </Link>
    </div>
  );
}
