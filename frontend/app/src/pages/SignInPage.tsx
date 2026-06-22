import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useNavigate, useLocation } from 'react-router-dom'
import { useState } from 'react'
import { useAuthStore } from '../store/auth'
import { Input, Button } from '../components/ui'
import { toast } from '../components/ui/Toast'

const schema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
  remember: z.boolean().optional(),
})

type FormValues = z.infer<typeof schema>

const FEATURES = [
  { icon: 'account_tree', text: 'Automated ASPICE documentation from source' },
  { icon: 'compare_arrows', text: 'Side-by-side diff review workflow' },
  { icon: 'group', text: 'Team collaboration with role-based access' },
  { icon: 'history', text: 'Full version history per git tag' },
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

  return (
    <div className="h-screen flex overflow-hidden">
      {/* Left panel */}
      <div className="hidden lg:flex w-[480px] flex-shrink-0 flex-col justify-between p-12 bg-primary">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-secondary flex items-center justify-center flex-shrink-0" style={{ borderRadius: 10 }}>
            <span className="material-symbols-outlined sym-fill text-white" style={{ fontSize: 20 }} aria-hidden>account_tree</span>
          </div>
          <span className="text-white font-bold text-lg tracking-tight">[PRODUCT NAME]</span>
        </div>

        <div>
          <h1 className="text-4xl font-bold text-white leading-tight mb-3">
            ASPICE compliance,<br />automated.
          </h1>
          <p className="text-white/60 text-sm leading-relaxed mb-10">
            Generate, review, and approve software design documentation directly from your C++ codebase.
          </p>
          <ul className="space-y-4">
            {FEATURES.map(({ icon, text }) => (
              <li key={icon} className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-white/10 flex items-center justify-center flex-shrink-0">
                  <span className="material-symbols-outlined text-white/80" style={{ fontSize: 16 }} aria-hidden>{icon}</span>
                </div>
                <span className="text-sm text-white/75">{text}</span>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-white/30">© 2025 [PRODUCT NAME]. For automotive Tier 1 suppliers.</p>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex items-center justify-center p-8 bg-surface-container-lowest">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-8 h-8 bg-secondary flex items-center justify-center" style={{ borderRadius: 8 }}>
              <span className="material-symbols-outlined sym-fill text-white" style={{ fontSize: 16 }} aria-hidden>account_tree</span>
            </div>
            <span className="text-primary font-bold text-base">[PRODUCT NAME]</span>
          </div>

          <h2 className="text-2xl font-bold text-on-surface mb-1">Welcome back</h2>
          <p className="text-sm text-on-surface-variant mb-8">Sign in to your account to continue.</p>

          {/* SSO */}
          <Button variant="outline" size="lg" className="w-full mb-6" type="button">
            <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden>corporate_fare</span>
            Continue with SSO
          </Button>

          <div className="flex items-center gap-3 mb-6">
            <div className="flex-1 h-px bg-outline-variant" />
            <span className="text-xs text-on-surface-variant">or</span>
            <div className="flex-1 h-px bg-outline-variant" />
          </div>

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
            <Input
              label="Work email"
              type="email"
              placeholder="you@company.com"
              autoComplete="email"
              leadingIcon="mail"
              error={errors.email?.message}
              {...register('email')}
            />
            <Input
              label="Password"
              type={showPassword ? 'text' : 'password'}
              placeholder="••••••••"
              autoComplete="current-password"
              leadingIcon="lock"
              trailingIcon={showPassword ? 'visibility_off' : 'visibility'}
              onTrailingClick={() => setShowPassword((v) => !v)}
              error={errors.password?.message}
              {...register('password')}
            />

            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" className="accent-secondary" {...register('remember')} />
                <span className="text-xs text-on-surface-variant">Remember me</span>
              </label>
              <button type="button" className="text-xs text-secondary hover:underline">
                Forgot password?
              </button>
            </div>

            <Button type="submit" size="lg" loading={isSubmitting} className="w-full mt-2">
              Sign in
            </Button>
          </form>
        </div>
      </div>
    </div>
  )
}
