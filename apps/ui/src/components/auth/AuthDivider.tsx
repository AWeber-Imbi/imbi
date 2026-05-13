export function AuthDivider() {
  return (
    <div className="relative my-6">
      <div className="absolute inset-0 flex items-center">
        <div className="w-full border-t border-gray-300"></div>
      </div>
      <div className="relative flex justify-center text-sm">
        <span className="text-muted-foreground bg-white px-2">
          Or sign in with local account
        </span>
      </div>
    </div>
  )
}
