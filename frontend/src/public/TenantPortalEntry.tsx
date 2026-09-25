import { Building2, CheckCircle2, Home, KeyRound, RefreshCw, ShieldCheck, XCircle } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { ApiError, publicApiRequest, TENANT_PORTAL_AUTH_EVENT } from '../api/client'
import { OwnerPortalPage } from './OwnerPortalPage'
import { TenantPortalPage } from './TenantPortalPage'
import './tenant-portal.css'
import './tenant-portal-auth.css'
import './owner-portal.css'

type AuthState = 'checking' | 'anonymous' | 'changing' | 'authenticated'
type PortalRole = 'tenant'|'owner'
type PortalContext = {person_id:string;person_name:string;roles:PortalRole[]}
type LoginResponse = {person_name:string;login_identifier:string|null;must_change_password:boolean;change_token?:string;change_token_expires_in_seconds?:number}

function messageFrom(cause: unknown, fallback: string) { return cause instanceof ApiError ? cause.detail : fallback }

export function TenantPortalEntry() {
  const [authState,setAuthState]=useState<AuthState>('checking')
  const [identifier,setIdentifier]=useState('')
  const [changeToken,setChangeToken]=useState('')
  const [personName,setPersonName]=useState('')
  const [context,setContext]=useState<PortalContext|null>(null)
  const [selectedRole,setSelectedRole]=useState<PortalRole|null>(null)

  async function resolvePortal(){
    const next=await publicApiRequest<PortalContext>('/portal-context')
    setContext(next)
    if(next.roles.length===1)setSelectedRole(next.roles[0])
    else setSelectedRole(null)
    setAuthState('authenticated')
  }

  useEffect(()=>{
    let active=true
    const requireAuth=()=>{if(!active)return;setAuthState('anonymous');setChangeToken('');setContext(null);setSelectedRole(null)}
    window.addEventListener(TENANT_PORTAL_AUTH_EVENT,requireAuth)
    void publicApiRequest('/tenant-portal/me').then(async()=>{if(active)await resolvePortal()}).catch(()=>{if(active)setAuthState('anonymous')})
    return()=>{active=false;window.removeEventListener(TENANT_PORTAL_AUTH_EVENT,requireAuth)}
  },[])

  if(authState==='checking')return <main className="tenant-login-shell"><div className="tenant-loading"><div className="tenant-brand-mark">IM</div><strong>Preparando seu portal...</strong></div></main>
  if(authState==='changing')return <TenantPasswordChange identifier={identifier} changeToken={changeToken} personName={personName} onChanged={()=>void resolvePortal()} onBack={()=>{setChangeToken('');setAuthState('anonymous')}}/>
  if(authState==='authenticated'){
    if(!context||context.roles.length===0)return <PortalWithoutRole onLogout={async()=>{await publicApiRequest('/tenant-portal/auth/logout',{method:'POST'});setAuthState('anonymous')}}/>
    if(context.roles.length>1&&!selectedRole)return <PortalRoleChooser name={context.person_name} onChoose={setSelectedRole} onLogout={async()=>{await publicApiRequest('/tenant-portal/auth/logout',{method:'POST'});setAuthState('anonymous')}}/>
    if(selectedRole==='owner')return <OwnerPortalPage onSwitchRole={context.roles.length>1?()=>setSelectedRole(null):undefined}/>
    if(context.roles.length>1)return <><button type="button" className="portal-floating-role-switch" onClick={()=>setSelectedRole(null)}><RefreshCw size={14}/><span>Trocar área</span></button><TenantPortalPage /></>
    return <TenantPortalPage />
  }
  return <PortalAuth onAuthenticated={()=>void resolvePortal()} onTemporaryLogin={(nextIdentifier,token,name)=>{setIdentifier(nextIdentifier);setChangeToken(token);setPersonName(name);setAuthState('changing')}}/>
}

function PortalAuth({onAuthenticated,onTemporaryLogin}:{onAuthenticated:()=>void;onTemporaryLogin:(identifier:string,token:string,personName:string)=>void}){
  const [identifier,setIdentifier]=useState(''),[password,setPassword]=useState(''),[error,setError]=useState(''),[saving,setSaving]=useState(false)
  async function login(event:FormEvent){event.preventDefault();setSaving(true);setError('');try{const result=await publicApiRequest<LoginResponse>('/tenant-portal/auth/document-login',{method:'POST',body:JSON.stringify({identifier,password})});if(result.must_change_password&&result.change_token)onTemporaryLogin(identifier,result.change_token,result.person_name);else onAuthenticated()}catch(cause){setError(messageFrom(cause,'Não foi possível entrar no portal.'))}finally{setSaving(false)}}
  return <main className="tenant-login-shell"><section className="tenant-login-card tenant-auth-card"><div className="tenant-login-brand"><div className="tenant-brand-mark">IM</div><div><strong>Portal do Cliente</strong><span>Acesso seguro aos seus imóveis e locações</span></div></div><div className="tenant-login-copy"><span className="tenant-eyebrow">Bem-vindo</span><h1>Tudo o que importa, em um só lugar.</h1><p>Acesse sua locação ou acompanhe seus imóveis, contratos e repasses como proprietário.</p></div>{error&&<div className="tenant-alert danger"><XCircle size={16}/><span>{error}</span></div>}<form onSubmit={login}><label><span>CPF ou CNPJ</span><input value={identifier} onChange={event=>setIdentifier(event.target.value)} autoComplete="username" inputMode="numeric" required placeholder="Digite seu CPF ou CNPJ"/></label><label><span>Senha</span><input type="password" value={password} onChange={event=>setPassword(event.target.value)} autoComplete="current-password" minLength={8} maxLength={200} required placeholder="Sua senha"/></label><button className="tenant-primary" disabled={saving}>{saving?'Entrando...':'Entrar no portal'}</button></form><div className="tenant-alert neutral tenant-auth-guidance"><KeyRound size={16}/><span><strong>Primeiro acesso?</strong> Use a senha temporária fornecida pela imobiliária. Você criará sua senha pessoal antes de entrar.</span></div><small>Esqueceu sua senha? Solicite uma nova senha temporária à imobiliária.</small></section></main>
}

function PortalRoleChooser({name,onChoose,onLogout}:{name:string;onChoose:(role:PortalRole)=>void;onLogout:()=>Promise<void>}){
 return <main className="tenant-login-shell"><section className="tenant-login-card tenant-auth-card"><div className="tenant-login-brand"><div className="tenant-brand-mark">IM</div><div><strong>Portal do Cliente</strong><span>Escolha a área que deseja acessar</span></div></div><div className="tenant-login-copy"><span className="tenant-eyebrow">Olá, {name.split(' ')[0]}</span><h1>Como você quer entrar?</h1><p>Seu cadastro possui mais de um vínculo com a imobiliária.</p></div><div className="portal-role-choice"><button className="portal-role-card" onClick={()=>onChoose('tenant')}><Home size={22}/><strong>Área do Inquilino</strong><span>Pagamentos, contrato, documentos, vistorias e manutenção da sua locação.</span></button><button className="portal-role-card" onClick={()=>onChoose('owner')}><Building2 size={22}/><strong>Área do Proprietário</strong><span>Imóveis, contratos, prestação de contas, repasses e manutenções.</span></button></div><button type="button" className="tenant-auth-back" onClick={()=>void onLogout()}>Sair</button></section></main>
}

function PortalWithoutRole({onLogout}:{onLogout:()=>Promise<void>}){
 return <main className="tenant-login-shell"><section className="tenant-login-card tenant-auth-card"><div className="tenant-alert danger"><XCircle size={16}/><span>Seu acesso existe, mas não há locação ou imóvel vinculado a este cadastro. Entre em contato com a imobiliária.</span></div><button className="tenant-secondary" onClick={()=>void onLogout()}>Sair</button></section></main>
}

function TenantPasswordChange({identifier,changeToken,personName,onChanged,onBack}:{identifier:string;changeToken:string;personName:string;onChanged:()=>void;onBack:()=>void}){
  const [newPassword,setNewPassword]=useState(''),[confirmPassword,setConfirmPassword]=useState(''),[error,setError]=useState(''),[saving,setSaving]=useState(false)
  async function submit(event:FormEvent){event.preventDefault();setError('');if(newPassword!==confirmPassword){setError('As senhas informadas não coincidem.');return}setSaving(true);try{await publicApiRequest('/tenant-portal/auth/temporary-change',{method:'POST',body:JSON.stringify({identifier,change_token:changeToken,password:newPassword})});onChanged()}catch(cause){setError(messageFrom(cause,'Não foi possível criar sua senha pessoal.'))}finally{setSaving(false)}}
  return <main className="tenant-login-shell"><section className="tenant-login-card tenant-auth-card"><div className="tenant-login-brand"><div className="tenant-brand-mark">IM</div><div><strong>Portal do Cliente</strong><span>Acesso seguro aos seus vínculos</span></div></div><div className="tenant-login-copy"><span className="tenant-eyebrow">Primeiro acesso</span><h1>Crie sua senha pessoal.</h1><p>{personName?`${personName}, `:''}a senha temporária foi aceita. Escolha agora a senha que você usará nos próximos acessos.</p></div><div className="tenant-alert success"><CheckCircle2 size={16}/><span>Senha temporária validada com segurança.</span></div>{error&&<div className="tenant-alert danger"><XCircle size={16}/><span>{error}</span></div>}<form onSubmit={submit}><label><span>Nova senha</span><input type="password" value={newPassword} onChange={event=>setNewPassword(event.target.value)} autoComplete="new-password" minLength={8} maxLength={200} required placeholder="Mínimo de 8 caracteres"/></label><label><span>Confirmar nova senha</span><input type="password" value={confirmPassword} onChange={event=>setConfirmPassword(event.target.value)} autoComplete="new-password" minLength={8} maxLength={200} required placeholder="Repita sua nova senha"/></label><button className="tenant-primary" disabled={saving||newPassword.length<8}>{saving?'Salvando...':'Criar minha senha'}</button></form><div className="tenant-alert neutral tenant-auth-guidance"><ShieldCheck size={16}/><span>A senha temporária deixará de funcionar assim que sua senha pessoal for criada.</span></div><button type="button" className="tenant-auth-back" disabled={saving} onClick={onBack}>Voltar para entrar</button></section></main>
}
