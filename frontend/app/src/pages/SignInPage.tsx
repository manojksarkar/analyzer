import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useNavigate, useLocation } from 'react-router-dom'
import { useState } from 'react'
import { useAuthStore } from '../store/auth'
import { toast } from '../components/ui/Toast'

const schema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
  remember: z.boolean().optional(),
})
type FormValues = z.infer<typeof schema>

const FEATURES = [
  'ASPICE Ready',
  'End-to-End Traceability',
  'Enterprise Security',
]

export function SignInPage() {
  const { signIn } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: Location })?.from?.pathname ?? '/projects'
  const [showPassword, setShowPassword] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  async function onSubmit(data: FormValues) {
    try {
      await signIn(data.email, data.password)
      navigate(from, { replace: true })
    } catch {
      toast.error('Sign-in failed', 'Check your email and password.')
    }
  }

  const inputStyle: React.CSSProperties = {
    width: '100%',
    height: 44,
    padding: '0 12px',
    background: '#fff',
    border: '1px solid #c4c6cd',
    borderRadius: 12,
    fontFamily: 'Inter, sans-serif',
    fontSize: 14,
    color: '#0b1c30',
    outline: 'none',
  }

  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color: '#44474c',
    marginBottom: 6,
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-background">
      <div
        className="w-full bg-white border border-outline-variant rounded-xl overflow-hidden grid"
        style={{
          maxWidth: 900,
          gridTemplateColumns: '1fr 1.1fr',
          boxShadow: '0 4px 32px rgba(4,22,39,.10)',
        }}
      >
        {/* Left Panel */}
        <div className="hidden lg:flex flex-col justify-between p-12 bg-primary text-white">
          <div>
            {/* Logo */}
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 bg-secondary rounded-lg flex items-center justify-center flex-shrink-0">
                <span className="material-symbols-outlined sym-fill text-white" style={{ fontSize: 18 }} aria-hidden>account_tree</span>
              </div>
              <div>
                <h1 className="font-bold tracking-tight" style={{ fontFamily: 'Inter', fontSize: 15, lineHeight: 1.2 }}>[PRODUCT NAME]</h1>
                <p className="text-on-primary-container uppercase mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.08em' }}>Automotive Tier 1</p>
              </div>
            </div>

            {/* Headline */}
            <div className="mt-14">
              <p className="text-secondary-container uppercase mb-4" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.2em' }}>AI Software Intelligence Platform</p>
              <h2 className="text-white leading-tight" style={{ fontSize: 28, lineHeight: '36px', fontWeight: 700 }}>
                Turn your codebase into compliance — automatically.
              </h2>
              <p className="mt-4 text-on-primary-container leading-relaxed" style={{ fontSize: 16, maxWidth: 340 }}>
                Generate requirements, architecture, traceability, test documentation, and compliance artifacts automatically.
              </p>
            </div>
          </div>

          {/* Feature list */}
          <div className="flex flex-col gap-2.5 mt-10">
            {FEATURES.map((feat) => (
              <div key={feat} className="flex items-center gap-2.5">
                <span className="material-symbols-outlined sym-fill text-on-tertiary-container" style={{ fontSize: 16 }} aria-hidden>check_circle</span>
                <span className="text-on-primary-container" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 500 }}>{feat}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right Panel */}
        <div className="p-10 lg:p-14 flex items-center justify-center">
          <div className="w-full" style={{ maxWidth: 360 }}>

            {/* Mobile logo */}
            <div className="lg:hidden flex items-center gap-3 mb-8">
              <div className="w-8 h-8 bg-secondary rounded-lg flex items-center justify-center flex-shrink-0">
                <span className="material-symbols-outlined sym-fill text-white" style={{ fontSize: 18 }} aria-hidden>account_tree</span>
              </div>
              <h1 className="text-primary font-bold tracking-tight" style={{ fontFamily: 'Inter', fontSize: 15 }}>[PRODUCT NAME]</h1>
            </div>

            {/* Heading */}
            <div className="mb-8">
              <h2 className="text-on-surface" style={{ fontSize: 24, fontWeight: 600, lineHeight: '32px', letterSpacing: '-0.01em' }}>Sign in to continue</h2>
              <p className="text-on-surface-variant mt-1.5" style={{ fontSize: 14 }}>Access your workspace.</p>
            </div>

            {/* SSO Button */}
            <button
              type="button"
              onClick={() => navigate(from, { replace: true })}
              className="w-full flex items-center justify-center gap-2.5 h-11 rounded-xl border border-outline-variant bg-white hover:bg-surface-container-low transition-colors mb-5"
              style={{ fontFamily: 'Inter', fontSize: 13, fontWeight: 500, color: '#0b1c30' }}
            >
              <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 18 }} aria-hidden>domain</span>
              Continue with Company SSO
            </button>

            {/* Divider */}
            <div className="flex items-center gap-3 mb-5">
              <div className="flex-1 border-t border-outline-variant" />
              <span className="text-on-surface-variant uppercase" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.08em' }}>or</span>
              <div className="flex-1 border-t border-outline-variant" />
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
              {/* Email */}
              <div>
                <label style={labelStyle}>Work Email</label>
                <input
                  type="email"
                  placeholder="name@company.com"
                  autoComplete="email"
                  style={inputStyle}
                  className="focus:border-secondary focus:shadow-[0_0_0_3px_rgba(0,88,190,0.12)]"
                  {...register('email')}
                />
                {errors.email && <p className="mt-1 text-error" style={{ fontSize: 12 }}>{errors.email.message}</p>}
              </div>

              {/* Password */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label style={{ ...labelStyle, marginBottom: 0 }}>Password</label>
                  <button type="button" className="text-secondary hover:underline" style={{ fontSize: 12 }}>Forgot password?</button>
                </div>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    placeholder="••••••••"
                    autoComplete="current-password"
                    style={{ ...inputStyle, paddingRight: 44 }}
                    className="focus:border-secondary focus:shadow-[0_0_0_3px_rgba(0,88,190,0.12)]"
                    {...register('password')}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface transition-colors"
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden>
                      {showPassword ? 'visibility' : 'visibility_off'}
                    </span>
                  </button>
                </div>
                {errors.password && <p className="mt-1 text-error" style={{ fontSize: 12 }}>{errors.password.message}</p>}
              </div>

              {/* Remember me */}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="remember"
                  className="w-4 h-4 rounded border-outline-variant cursor-pointer accent-secondary"
                  {...register('remember')}
                />
                <label htmlFor="remember" className="text-on-surface-variant cursor-pointer" style={{ fontSize: 13 }}>Remember me</label>
              </div>

              {/* Submit */}
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full h-11 rounded-xl bg-secondary text-white hover:bg-secondary-container transition-colors mt-1 disabled:opacity-60"
                style={{ fontFamily: 'Inter', fontSize: 13, fontWeight: 600 }}
              >
                {isSubmitting ? 'Signing in…' : 'Continue'}
              </button>
            </form>

            {/* Footer */}
            <div className="mt-8 pt-6 border-t border-outline-variant text-center">
              <p className="text-on-surface-variant" style={{ fontSize: 13 }}>
                New to the platform?{' '}
                <a href="#" className="text-secondary font-medium hover:underline">Request Access</a>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
