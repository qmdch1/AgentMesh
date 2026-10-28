import { spawn } from 'node:child_process';
import { readFileSync, mkdirSync, writeFileSync, appendFileSync, existsSync, realpathSync } from 'node:fs';
import { resolve, dirname, relative, isAbsolute, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeScopedText } from '../../scripts/agentmesh/scoped_write.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const state = resolve(root, '.agentmesh');
const profiles = JSON.parse(readFileSync(resolve(root, 'scripts/agentmesh/profiles.json'), 'utf8'));

export default function(pi: any) {
  const z = pi.zod;
  pi.setLabel('AgentMesh');
  pi.registerProvider('agentmesh-local', {
    baseUrl: 'http://127.0.0.1:18541/v1', apiKey: 'agentmesh-loopback', api: 'openai-completions',
    models: [{ id: 'default_model', name: 'Qwen3.6-35B-A3B · MLX 4bit', api: 'openai-completions',
      input: ['text'], reasoning: true, contextWindow: 16384, maxTokens: 4096, compactionModel: 'agentmesh-local/default_model',
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      thinking: { mode: 'effort', efforts: ['high'], defaultLevel: 'high', requiresEffort: false },
      compat: { thinkingFormat: 'qwen-chat-template', supportsReasoningEffort: false, supportsDeveloperRole: false,
        maxTokensField: 'max_tokens', supportsStore: false, reasoningContentField: 'reasoning' } }],
  });
  const worker = process.env.AGENTMESH_WORKER === '1';
  const spec = worker && process.env.AGENTMESH_WORKER_SPEC
    ? JSON.parse(readFileSync(process.env.AGENTMESH_WORKER_SPEC, 'utf8')) : null;
  pi.on('session_start', async (_event: any, ctx: any) => {
    pi.setServiceTier('anthropic', undefined);
    pi.setServiceTier('openai', 'priority');
    if (worker) return;
    const model = ctx.models.resolve(profiles.coordinator.model);
    if (!model || !(await pi.setModel(model))) throw new Error('AgentMesh: Claude Opus 5.5 is unavailable. Run /mesh-doctor.');
    pi.setThinkingLevel('high');
    const names = new Set(pi.getAllTools().map((t: any) => t.name));
    await pi.setActiveTools(['read', 'grep', 'glob', 'web_search', 'mesh_run', 'mesh_status', 'mesh_doctor'].filter(n => names.has(n)));
    ctx.ui.setStatus('agentmesh', 'AgentMesh · Opus 5.5 high · Codex Fast');
  });
  pi.on('before_provider_request', async (event: any, ctx: any) => {
    const p={...event.payload};
    if (ctx.model?.provider==='anthropic') { delete p.speed; if(['priority','fast'].includes(p.service_tier)) delete p.service_tier; }
    if (ctx.model?.provider==='openai-codex') p.service_tier='priority';
    mkdirSync(state,{recursive:true,mode:0o700});
    appendFileSync(resolve(state,'request-audit.jsonl'),JSON.stringify({time:new Date().toISOString(),worker,provider:ctx.model?.provider,model:ctx.model?.id,service_tier:p?.service_tier ?? null,speed:p?.speed ?? null,thinking_enabled:p?.chat_template_kwargs?.enable_thinking ?? null,effort:p?.reasoning?.effort ?? p?.output_config?.effort ?? null})+'\n',{mode:0o600});
    return p;
  });
  pi.on('before_agent_start' , async (_event: any, ctx: any) => {
    if (!worker) {
      const model=ctx.models.resolve(profiles.coordinator.model);
      if(!model || !(await pi.setModel(model))) throw new Error('Required coordinator model unavailable');
      pi.setThinkingLevel('high');
    }
    return { systemPrompt: readFileSync(resolve(root, `scripts/agentmesh/${worker ? 'worker' : 'coordinator'}.md`), 'utf8') };
  });
  if (worker) {
    if (spec?.task?.profile === 'local') pi.registerTool({
      name:'mesh_write', label:'Write scoped text',
      description:'Write one allowed UTF-8 text file atomically. Supply an array of lines WITHOUT line separators; set final_newline=true for one ending LF. This preserves whitespace despite XML tool-parser delimiters. No shell is available. Example: lines=["연결하기"], final_newline=true produces exactly 13 UTF-8 bytes.',
      parameters:z.object({path:z.string(),lines:z.array(z.string()),final_newline:z.boolean().default(true)}),
      execute:async (_id: string,p: any,_signal: AbortSignal,_update: any,ctx: any)=>{
        const result=writeScopedText(ctx.cwd,spec.task.write_paths || [],p);
        return {content:[{type:'text',text:JSON.stringify(result)}],details:result};
      },
    });
    pi.on('tool_call', async (event: any, ctx: any) => {
      if (!['edit','write'].includes(event.toolName)) return;
      const input=event.input || {};
      const path=input.path || input.file_path || input.file;
      if (typeof path !== 'string') return {block:true, reason:'Cannot determine scoped write path'};
      let parent=resolve(ctx.cwd,path);
      const missing: string[]=[];
      while(!existsSync(parent) && dirname(parent)!==parent) { missing.unshift(basename(parent)); parent=dirname(parent); }
      const abs=resolve(realpathSync(parent),...missing);
      const rel=relative(realpathSync(ctx.cwd),abs);
      if (isAbsolute(rel) || rel==='..' || rel.startsWith('../') || !spec?.task?.write_paths?.some((p: string) => rel===p.replace(/\/$/,'') || rel.startsWith(p.replace(/\/$/,'')+'/')))
        return {block:true,reason:'Outside task write_paths; return to coordinator for reassignment'};
    });
    return;
  }
  function invoke(action: string, payload: any, signal: AbortSignal | undefined, onUpdate?: any): Promise<any> {
    mkdirSync(state,{recursive:true,mode:0o700});
    const args=[resolve(root,'scripts/agentmesh/runtime.py'),action];
    if (action==='run') {
      const request=resolve(state,`request-${crypto.randomUUID()}.json`);
      writeFileSync(request,JSON.stringify(payload),{mode:0o600});args.push('--request',request);
    } else if(payload?.run_id) args.push('--run-id',payload.run_id);
    return new Promise((done,fail) => {
      const p=spawn('/usr/bin/python3',args,{cwd:root,stdio:['ignore','pipe','pipe'],detached:true});
      let output='',error='';
      const abort=()=>{try{process.kill(-p.pid!,'SIGTERM');}catch{}};
      signal?.addEventListener('abort',abort,{once:true});
      p.stdout.on('data',chunk=>{output+=chunk.toString(); onUpdate?.({content:[{type:'text',text:chunk.toString()}]});});
      p.stderr.on('data',chunk=>{error+=chunk.toString();});
      p.on('error',fail);
      p.on('close',code=>{
        signal?.removeEventListener('abort',abort);
        const line=output.trim().split('\n').at(-1) || '{}';
        let result;try{result=JSON.parse(line);}catch{result={status:'error',error:error || output};}
        done({content:[{type:'text',text:JSON.stringify(result)}],details:result,isError:code!==0 || ['error','incomplete'].includes(result.status)});
      });
    });
  }
  const task=z.object({id:z.string(),profile:z.enum(['code','code_deep','hard','hard_deep','design','design_deep','local']),instruction:z.string(),acceptance:z.array(z.string()).min(1),depends_on:z.array(z.string()).default(() => []),context_files:z.array(z.string()).default(() => []),context_images:z.array(z.string()).default(() => []),read_paths:z.array(z.string()).default(() => []),write_paths:z.array(z.string()).default(() => []),checks:z.array(z.array(z.string())).default(() => []),scope_confirmed:z.boolean().default(false)});
  pi.registerTool({name:'mesh_run',label:'AgentMesh parts',description:'Execute a scoped task DAG using fixed OMP worker models, collect results and run verification. Read-only parts run concurrently; writing parts run serially. Retry an existing run_id with the COMPLETE revised plan; successful unchanged parts are reused. Never use this tool to summarize a plan instead of doing work.',parameters:z.object({plan:z.object({workspace:z.string(),common_context:z.string(),tasks:z.array(task).min(1).max(16),task_timeout:z.number().int().min(30).max(1200).default(600),run_timeout:z.number().int().min(60).max(7200).default(1800)}),run_id:z.string().optional()}),execute:async (_id: string,params: any,signal: AbortSignal,onUpdate: any)=>invoke('run',params,signal,onUpdate)});
  for (const action of ['status','doctor']) pi.registerTool({name:`mesh_${action}`,label:`AgentMesh ${action}`,description:action==='status'?'Read durable task results and interruption checkpoints.':'Inspect configured worker models and local installation (does not claim cloud inference works).',parameters:z.object({run_id:z.string().optional()}),execute:async (_id: string,p: any,s: AbortSignal)=>invoke(action,p,s)});
  pi.registerCommand('mesh-doctor',{description:'AgentMesh connection and installation status',handler:async (_args: string,ctx: any)=>{const result=await invoke('doctor',{},undefined);ctx.ui.notify(result.content[0].text,'info');}});
}
