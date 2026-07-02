import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useNavigate, useLocation } from 'react-router-dom'
import { useId, useState } from 'react'
import { useAuthStore } from '../store/auth'
import { ApiError } from '../lib/http'
import { Icon, toast } from '../components/ui'
import { cn } from '../lib/cn'
import { APP_NAME, APP_TAGLINE } from '../constants/branding'

const schema = z.object({
  email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
  remember: z.boolean().optional(),
})
type FormValues = z.infer<typeof schema>

const FEATURES = ['ASPICE Ready', 'End-to-End Traceability', 'Enterprise Security']

const INPUT_CLS = 'w-full h-11 px-3 bg-white border border-outline-variant rounded-2xl font-sans text-sm text-on-surface outline-none focus:border-secondary focus:shadow-[0_0_0_3px_rgba(0,88,190,0.12)]'
const LABEL_CLS = 'block font-mono text-caption font-semibold tracking-[0.08em] uppercase text-on-surface-variant mb-1.5'

/** Turn any sign-in failure into a clear, user-facing message. */
function signInErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403) return 'Invalid email or password.'
    if (err.status === 429) return 'Too many attempts. Please wait a moment and try again.'
    if (err.status >= 500) return 'The server had a problem. Please try again shortly.'
    return err.message // other 4xx — backend message is meaningful
  }
  // fetch() rejects with a TypeError when the network/server is unreachable.
  if (err instanceof TypeError) return "Can't reach the server. Check your connection and try again."
  return 'Something went wrong. Please try again.'
}

export function SignInPage() {
  const { signIn } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: Location })?.from?.pathname ?? '/projects'
  const [showPassword, setShowPassword] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)

  const emailId = useId()
  const passwordId = useId()
  const emailErrId = useId()
  const passwordErrId = useId()

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const busy = isSubmitting

  async function onSubmit(data: FormValues) {
    setAuthError(null)
    try {
      await signIn(data.email, data.password, data.remember ?? false)
      navigate(from, { replace: true })
    } catch (err) {
      const message = signInErrorMessage(err)
      setAuthError(message)
      toast.error('Sign-in failed', message)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-background">
      <div className="w-full max-w-5xl bg-white border border-outline-variant rounded-xl overflow-hidden grid lg:grid-cols-[1fr_1.1fr] shadow-[0_4px_32px_rgba(4,22,39,.10)]">
        {/* Left Panel */}
        <div className="hidden lg:flex flex-col justify-between p-12 bg-primary text-white">
          <div>
            {/* Logo */}
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 bg-secondary rounded-lg flex items-center justify-center flex-shrink-0">
                <Icon name="account_tree" size={18} fill className="text-white" />
              </div>
              <div>
                <h1 className="font-bold tracking-tight font-sans text-title leading-[1.2]">{APP_NAME}</h1>
                <p className="text-on-primary-container uppercase mt-0.5 font-mono text-caption font-medium tracking-[0.08em]">{APP_TAGLINE}</p>
              </div>
            </div>

            {/* Headline */}
            <div className="mt-14">
              <p className="text-secondary-container uppercase mb-4 font-mono text-caption font-medium tracking-[0.2em]">AI Software Intelligence Platform</p>
              <h2 className="text-white text-[28px] leading-[36px] font-bold tracking-[-0.02em]">
                Turn your codebase into compliance — automatically.
              </h2>
              <p className="mt-4 text-on-primary-container leading-relaxed text-base max-w-[340px]">
                Generate requirements, architecture, traceability, test documentation, and compliance artifacts automatically.
              </p>
            </div>
          </div>

          {/* Feature list */}
          <ul className="flex flex-col gap-2.5 mt-10">
            {FEATURES.map((feat) => (
              <li key={feat} className="flex items-center gap-2.5">
                <Icon name="check_circle" size={16} fill className="text-on-tertiary-container" />
                <span className="text-on-primary-container font-mono text-xs font-medium">{feat}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Right Panel */}
        <div className="p-10 lg:p-14 flex items-center justify-center">
          <div className="w-full max-w-[360px]">

            {/* Mobile logo */}
            <div className="lg:hidden flex items-center gap-3 mb-8">
              <div className="w-8 h-8 bg-secondary rounded-lg flex items-center justify-center flex-shrink-0">
                <Icon name="account_tree" size={18} fill className="text-white" />
              </div>
              <h1 className="text-primary font-bold tracking-tight font-sans text-title">{APP_NAME}</h1>
            </div>

            {/* Heading */}
            <div className="mb-8">
              <h2 className="text-on-surface text-2xl font-semibold leading-[32px] tracking-[-0.01em]">Sign in to continue</h2>
              <p className="text-on-surface-variant mt-1.5 text-sm">Access your workspace.</p>
            </div>

            {/* SSO Button — kept for layout; no backend endpoint yet (disabled). */}
            <button
              type="button"
              disabled
              title="Company SSO is not available yet"
              className="w-full flex items-center justify-center gap-2.5 h-11 rounded-xl border border-outline-variant bg-white transition-colors mb-5 opacity-60 cursor-not-allowed font-sans text-body font-medium text-on-surface"
            >
              <Icon name="domain" size={18} className="text-on-surface-variant" />
              Continue with Company SSO
            </button>

            {/* Divider */}
            <div className="flex items-center gap-3 mb-5">
              <div className="flex-1 border-t border-outline-variant" />
              <span className="text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.08em]">or</span>
              <div className="flex-1 border-t border-outline-variant" />
            </div>

            {/* Auth error banner */}
            {authError && (
              <div
                role="alert"
                className="mb-4 flex items-start gap-2 rounded-xl border border-error-container bg-error-container px-3 py-2.5"
              >
                <Icon name="error" size={18} className="text-on-error-container" />
                <p className="text-on-error-container text-body leading-[18px]">{authError}</p>
              </div>
            )}

            {/* Form */}
            <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4" aria-label="Sign in">
              {/* Work Email */}
              <div>
                <label htmlFor={emailId} className={LABEL_CLS}>Work Email</label>
                <input
                  id={emailId}
                  type="email"
                  placeholder="name@company.com"
                  autoComplete="email"
                  aria-invalid={errors.email ? 'true' : undefined}
                  aria-describedby={errors.email ? emailErrId : undefined}
                  className={INPUT_CLS}
                  {...register('email')}
                />
                {errors.email && <p id={emailErrId} className="mt-1 text-error text-xs">{errors.email.message}</p>}
              </div>

              {/* Password */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label htmlFor={passwordId} className={cn(LABEL_CLS, 'mb-0')}>Password</label>
                  <button
                    type="button"
                    onClick={() => toast.info('Password reset', 'Contact your administrator to reset your password.')}
                    className="text-secondary hover:underline text-xs"
                  >
                    Forgot password?
                  </button>
                </div>
                <div className="relative">
                  <input
                    id={passwordId}
                    type={showPassword ? 'text' : 'password'}
                    placeholder="••••••••"
                    autoComplete="current-password"
                    aria-invalid={errors.password ? 'true' : undefined}
                    aria-describedby={errors.password ? passwordErrId : undefined}
                    className={cn(INPUT_CLS, 'pr-11')}
                    {...register('password')}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    aria-pressed={showPassword}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface transition-colors"
                  >
                    <Icon name={showPassword ? 'visibility' : 'visibility_off'} size={18} />
                  </button>
                </div>
                {errors.password && <p id={passwordErrId} className="mt-1 text-error text-xs">{errors.password.message}</p>}
              </div>

              {/* Remember me */}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="remember"
                  className="w-4 h-4 rounded border-outline-variant cursor-pointer accent-secondary"
                  {...register('remember')}
                />
                <label htmlFor="remember" className="text-on-surface-variant cursor-pointer text-body">Remember me</label>
              </div>

              {/* Submit */}
              <button
                type="submit"
                disabled={busy}
                className="w-full h-11 rounded-xl bg-secondary text-white hover:bg-secondary-container transition-colors mt-1 disabled:opacity-60 disabled:cursor-not-allowed font-sans text-body font-semibold"
              >
                {isSubmitting ? 'Signing in…' : 'Continue'}
              </button>
            </form>

            {/* Footer */}
            <div className="mt-8 pt-6 border-t border-outline-variant text-center">
              <p className="text-on-surface-variant text-body">
                New to the platform?{' '}
                <button
                  type="button"
                  onClick={() => toast.info('Request access', 'Ask your workspace administrator to send you an invite.')}
                  className="text-secondary font-medium hover:underline"
                >
                  Request Access
                </button>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
