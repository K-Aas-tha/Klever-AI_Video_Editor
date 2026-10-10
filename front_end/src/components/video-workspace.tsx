import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronRight, Clapperboard, Download, Film, FolderOpen, Heart, Link2, LoaderCircle, MoreHorizontal, Plus, Search, Settings2, ShieldCheck, Sparkles, Upload, WandSparkles, X, Play, Image as ImageIcon, Scissors, Sliders } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Brand } from './brand';
import podcast from '@/assets/podcast.jpg';

const API_BASE = "http://localhost:8000";

type View = 'studio' | 'projects' | 'settings';

type TopicSlide = {
  topic_number: number;
  title: string;
  timestamp_sec: number;
  slide_image?: string;
  bullets?: string[];
};

type Summary = {
  topics_count: number;
  silences_cut: number;
  scenes_detected: number;
  final_duration_sec: number;
};

type Project = {
  id: number;
  jobId?: string;
  title: string;
  image: string;
  category: string;
  duration: string;
  clips: number;
  date: string;
  status: string;
  source?: string;
  fileName?: string;
  rawFile?: File;
  editedVideoUrl?: string;
  thumbnailUrl?: string;
  progress?: number;
  stepMessage?: string;
  topics?: TopicSlide[];
  summary?: Summary;
};

const demoProjects: Project[] = [
  { id: 1, title: 'The Creative Mind Podcast', image: podcast, category: 'Podcast', duration: '24:38', clips: 8, date: '2 hours ago', status: 'Ready' },
];

const navItems = [
  { id: 'studio', label: 'Create clips', icon: WandSparkles },
  { id: 'projects', label: 'My projects', icon: FolderOpen }
] as const;

export function VideoWorkspace() {
  const [view, setView] = useState<View>('studio');
  const [projects, setProjects] = useState<Project[]>(demoProjects);
  const [filter, setFilter] = useState('All projects');
  const [search, setSearch] = useState('');
  const [url, setUrl] = useState('');
  const [notice, setNotice] = useState('');
  const [dragging, setDragging] = useState(false);
  const [active, setActive] = useState<Project | null>(null);
  const [menu, setMenu] = useState<number | null>(null);
  
  // Editor Form States
  const [title, setTitle] = useState('');
  const [prompt, setPrompt] = useState('Create a concise edit. Keep key insights and necessary context; remove pauses, filler, repetition, redundant examples, greetings, and tangents.');
  const [removeSilence, setRemoveSilence] = useState(true);
  const [insertSlides, setInsertSlides] = useState(true);
  const [slideDuration, setSlideDuration] = useState(3.5);
  const [format, setFormat] = useState('9:16');
  
  // Processing States
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [stepMessage, setStepMessage] = useState('');
  const [editorNotice, setEditorNotice] = useState('');
  const [workspaceName, setWorkspaceName] = useState('My workspace');
  const [name, setName] = useState('Alex Morgan');
  const [saved, setSaved] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);
  const uploadRef = useRef<HTMLElement>(null);
  const objects = useRef<string[]>([]);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => () => {
    objects.current.forEach(value => URL.revokeObjectURL(value));
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
  }, []);

  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setActive(null); setMenu(null); }
    };
    window.addEventListener('keydown', handle);
    return () => window.removeEventListener('keydown', handle);
  }, []);

  function open(project: Project) {
    setActive(project);
    setTitle(project.title);
    setEditorNotice('');
    setProgress(project.progress || 0);
    setStepMessage(project.stepMessage || '');
  }

  function startProject() {
    setView('studio');
    setNotice('');
    setTimeout(() => {
      uploadRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      fileRef.current?.click();
    }, 50);
  }

  async function upload(file?: File) {
    if (!file) return;
    if (!file.type.startsWith('video/')) {
      setNotice('Please choose a valid video file (MP4, MOV, WebM).');
      return;
    }
    if (file.size > 500 * 1024 * 1024) {
      setNotice('Please select a video smaller than 500 MB.');
      return;
    }

    const source = URL.createObjectURL(file);
    objects.current.push(source);
    setNotice('Uploading video to Klever AI server...');

    const tempJobId = `job_${Date.now()}`;
    const newProject: Project = {
      id: Date.now(),
      jobId: tempJobId,
      title: file.name.replace(/\.[^.]+$/, ''),
      image: podcast,
      source,
      fileName: file.name,
      rawFile: file,
      category: 'Uploaded video',
      duration: 'New',
      clips: 0,
      date: 'Just now',
      status: 'Draft'
    };

    setProjects(current => [newProject, ...current]);
    open(newProject);
    setNotice('');

    // Upload to FastAPI Backend
    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${API_BASE}/api/upload`, {
        method: "POST",
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        const serverJobId = data.job_id;
        
        setProjects(current => current.map(p => p.id === newProject.id ? { ...p, jobId: serverJobId } : p));
        setActive(prev => prev && prev.id === newProject.id ? { ...prev, jobId: serverJobId } : prev);
        setEditorNotice("Video uploaded to backend. Ready for AI processing!");
      }
    } catch (err) {
      console.warn("Backend upload note:", err);
      setEditorNotice("Video ready locally. FastAPI server connectable at http://localhost:8000.");
    }
  }

  async function triggerAIProcessing() {
    if (!active) return;
    setBusy(true);
    setProgress(10);
    setStepMessage("Initializing Klever AI Editing Engine...");

    let currentJobId = active.jobId;

    // If job ID not yet registered on backend, upload first
    if (!currentJobId && active.rawFile) {
      try {
        const formData = new FormData();
        formData.append("file", active.rawFile);
        const uploadRes = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: formData });
        if (uploadRes.ok) {
          const uData = await uploadRes.json();
          currentJobId = uData.job_id;
        }
      } catch (e) {
        console.error("Upload error before process:", e);
      }
    }

    if (!currentJobId) {
      // Fallback mock simulation if offline
      simulateLocalAIProcess();
      return;
    }

    try {
      const processForm = new FormData();
      processForm.append("job_id", currentJobId);
      processForm.append("prompt", prompt);
      processForm.append("remove_silence", String(removeSilence));
      processForm.append("insert_slides", String(insertSlides));
      processForm.append("slide_duration", String(slideDuration));

      const processRes = await fetch(`${API_BASE}/api/process`, {
        method: "POST",
        body: processForm
      });

      if (!processRes.ok) {
        throw new Error("Could not start background processing pipeline.");
      }

      startStatusPolling(currentJobId);

    } catch (err) {
      console.error("AI Pipeline Trigger Error:", err);
      const message = err instanceof Error ? err.message : String(err);
      setEditorNotice("Error launching backend process: " + message);
      setBusy(false);
    }
  }

  function startStatusPolling(jobId: string) {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);

    pollTimerRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/status/${jobId}`);
        if (res.status === 404) {
          if (pollTimerRef.current) clearInterval(pollTimerRef.current);
          pollTimerRef.current = null;
          setBusy(false);
          setEditorNotice('This processing job is no longer available. Please start it again.');
          return;
        }
        if (!res.ok) return;

        const data = await res.json();
        const p = data.progress || 0;
        const msg = data.step_message || "Processing...";

        setProgress(p);
        setStepMessage(msg);

        if (data.status === "completed" && data.result) {
          if (pollTimerRef.current) clearInterval(pollTimerRef.current);
          setBusy(false);
          
          const result = data.result;
          const editedUrl = `${API_BASE}${result.edited_video_url}`;
          const thumbUrl = `${API_BASE}${result.thumbnail_url}`;
          
          // Form topics with absolute image URLs
          const formattedTopics = (result.topics || []).map((t: TopicSlide) => ({
            ...t,
            slide_image: t.slide_image ? `${API_BASE}${t.slide_image}` : thumbUrl
          }));

          setProjects(current => current.map(project => {
            if (project.id === active?.id) {
              return {
                ...project,
                status: 'Ready',
                clips: result.summary?.topics_count || 3,
                editedVideoUrl: editedUrl,
                thumbnailUrl: thumbUrl,
                topics: formattedTopics,
                summary: result.summary,
                progress: 100,
                stepMessage: 'AI Video Editing Completed!'
              };
            }
            return project;
          }));

          setActive(prev => prev ? {
            ...prev,
            status: 'Ready',
            clips: result.summary?.topics_count || 3,
            editedVideoUrl: editedUrl,
            thumbnailUrl: thumbUrl,
            topics: formattedTopics,
            summary: result.summary,
            progress: 100,
            stepMessage: 'AI Video Editing Completed!'
          } : null);

          setEditorNotice('AI Video Editing Complete! Preview your video with topic slides below.');
        } else if (data.status === "failed") {
          if (pollTimerRef.current) clearInterval(pollTimerRef.current);
          setBusy(false);
          setEditorNotice("Pipeline error: " + data.step_message);
        }
      } catch (e) {
        console.error("Status check failed:", e);
      }
    }, 1500);
  }

  function simulateLocalAIProcess() {
    let p = 10;
    const interval = setInterval(() => {
      p += 20;
      setProgress(p);
      if (p === 30) setStepMessage("Transcribing audio with OpenAI Whisper...");
      if (p === 50) setStepMessage("Detecting shot boundaries with PySceneDetect...");
      if (p === 70) setStepMessage("Generating topic slides...");
      if (p === 90) setStepMessage("Stitching video with MoviePy & FFmpeg...");

      if (p >= 100) {
        clearInterval(interval);
        setBusy(false);
        setProjects(current => current.map(project => 
          project.id === active?.id ? { ...project, clips: 3, status: 'Ready' } : project
        ));
        setEditorNotice('AI edits simulated. Start backend server at port 8000 for full video render.');
      }
    }, 800);
  }

  function download() {
    const targetUrl = active?.editedVideoUrl || active?.source;
    if (targetUrl) {
      const a = document.createElement('a');
      a.href = targetUrl;
      a.download = `klever_edited_${active?.title || 'video'}.mp4`;
      a.rel = 'noopener';
      a.click();
      setEditorNotice('Downloading edited video output file.');
    } else {
      setEditorNotice('No video source available for download.');
    }
  }

  const filtered = projects.filter(project => 
    (filter !== 'Ready' || project.status === 'Ready') && 
    project.title.toLowerCase().includes(search.toLowerCase())
  );
  const totalClips = projects.reduce((sum, project) => sum + project.clips, 0);

  function projectCards(items: Project[]) {
    return items.length ? (
      <div className="project-grid">
        {items.map(project => (
          <article className="project-card" key={project.id}>
            <div 
              className="project-cover" 
              role="button" 
              tabIndex={0} 
              aria-label={`Preview ${project.title}`} 
              onClick={() => open(project)}
            >
              {project.editedVideoUrl ? (
                <video src={project.editedVideoUrl} preload="metadata" muted />
              ) : project.source ? (
                <video src={project.source} preload="metadata" muted />
              ) : (
                <img src={project.image} alt={project.title} width={768} height={1024} loading="lazy" />
              )}
              <span className={`status-badge ${project.status === 'Ready' ? 'ready' : ''}`}>
                {project.status === 'Ready' && <Check size={10} />}
                {project.status}
              </span>
              <span className="cover-play"><Play size={15} fill="currentColor" /></span>
              <span className="duration">{project.duration}</span>
            </div>
            <div className="project-info">
              <div className="project-title-row">
                <h3 title={project.title}>{project.title}</h3>
                <Button 
                  variant="ghost" 
                  size="icon" 
                  className="project-menu" 
                  onClick={() => setMenu(menu === project.id ? null : project.id)}
                >
                  <MoreHorizontal />
                </Button>
              </div>
              <div className="project-meta">{project.category}<span>·</span>9:16</div>
              {menu === project.id && (
                <div className="flex gap-1 mt-2">
                  <Button variant="secondary" size="sm" onClick={() => { open(project); setMenu(null); }}>Edit AI Video</Button>
                  <Button variant="destructive" size="sm" onClick={() => { setProjects(current => current.filter(p => p.id !== project.id)); setMenu(null); }}>Delete</Button>
                </div>
              )}
              <div className="project-footer">
                <span className="clips-chip"><Film size={12} />{project.clips ? `${project.clips} clips` : 'No clips yet'}</span>
                <span>{project.date}</span>
              </div>
            </div>
          </article>
        ))}
      </div>
    ) : (
      <div className="empty-state">
        <FolderOpen className="mx-auto mb-3" />
        <p>No projects found.</p>
        <Button variant="link" onClick={startProject}>Create your first project</Button>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand />
        <Button variant="outline" className="workspace-select" onClick={() => setView('settings')}>
          <span className="flex items-center gap-2"><span className="workspace-avatar">M</span>{workspaceName}</span>
          <ChevronDown size={13} />
        </Button>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {navItems.map(item => (
            <Button key={item.id} variant="ghost" className={`nav-button ${view === item.id ? 'active' : ''}`} onClick={() => setView(item.id)}>
              <item.icon size={17} />{item.label}
              {item.id === 'projects' && <span className="nav-count">{projects.length}</span>}
            </Button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <Button variant="ghost" className="nav-button" onClick={() => setView('settings')}><Settings2 />Settings</Button>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="mobile-brand"><Brand /></div>
          <div className="breadcrumb">
            <span>Workspace</span>
            <ChevronRight size={12} />
            <strong>{view === 'studio' ? 'Create clips' : view === 'projects' ? 'My projects' : 'Settings'}</strong>
          </div>
          <div className="top-actions">
            <label className="search-field">
              <Search size={15} />
              <input placeholder="Search your projects…" value={search} onChange={e => setSearch(e.target.value)} />
            </label>
          </div>
        </header>

        <main className="main-content">
          {view === 'studio' ? (
            <>
              <div className="welcome-row">
                <div><h1>Cut the length, keep the impact!</h1><p>Automatic AI Video Editing Studio.</p></div>
                <Button className="new-project" onClick={startProject}><Plus size={15} />New project</Button>
              </div>

              <section className="creator-banner">
                <div className="banner-copy">
                  <h2>Long videos.<br /><span>AI Edited Magic.</span></h2>
                  <p>Automatic silence removal and shot detection.</p>
                </div>
              </section>

              <section ref={uploadRef}>
                <div className="section-heading">
                  <div><h2>Create your next AI video</h2><p>Upload a raw video file to process.</p></div>
                  <span className="date-chip"><ShieldCheck size={13} />FastAPI Engine</span>
                </div>

                <div className="upload-panel">
                  <div 
                    className={`drop-zone ${dragging ? 'dragging' : ''}`}
                    onDragOver={e => { e.preventDefault(); setDragging(true); }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={e => { e.preventDefault(); setDragging(false); upload(e.dataTransfer.files[0]); }}
                  >
                    <div className="upload-icon"><Upload size={21} /></div>
                    <h3>Drag & drop your video here</h3>
                    <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}><Plus size={13} />Choose a video</Button>
                  </div>
                </div>
                {notice && <p role="status" className="notice">{notice}</p>}
              </section>
            </>
          ) : (
            projectCards(filtered)
          )}
        </main>
      </div>

      <input ref={fileRef} type="file" accept="video/*" className="hidden" onChange={e => { upload(e.target.files?.[0]); e.target.value = ''; }} />

      {/* Editor Modal */}
      {active && (
        <div className="modal-overlay" onClick={() => setActive(null)}>
          <section className="studio-modal max-w-4xl" role="dialog" onClick={e => e.stopPropagation()}>
            <header className="modal-head">
              <div>
                <h2>Klever AI Video Editor Workspace</h2>
              </div>
              <Button variant="ghost" size="icon" onClick={() => setActive(null)}><X /></Button>
            </header>

            <div className="studio-body p-6 flex flex-col md:flex-row gap-6">
              {/* Video Player Box */}
              <div className="flex-1 flex flex-col gap-4">
                <div className="video-stage bg-black rounded-lg overflow-hidden max-h-[380px] flex items-center justify-center">
                  {active.editedVideoUrl ? (
                    <video src={active.editedVideoUrl} controls className="w-full h-full object-contain" />
                  ) : active.source ? (
                    <video src={active.source} controls className="w-full h-full object-contain" />
                  ) : (
                    <img src={active.image} alt={active.title} className="w-full h-full object-cover" />
                  )}
                </div>

                {/* Progress Track */}
                {busy && (
                  <div className="bg-slate-100 p-4 rounded-lg flex flex-col gap-2">
                    <div className="flex justify-between text-xs font-bold">
                      <span>{stepMessage}</span>
                      <span>{progress}%</span>
                    </div>
                    <div className="w-full bg-slate-200 h-2 rounded-full overflow-hidden">
                      <div className="bg-primary h-full transition-all duration-300" style={{ width: `${progress}%` }} />
                    </div>
                  </div>
                )}

                {/* Topics Breakdown Gallery */}
                {active.topics && active.topics.length > 0 && (
                  <div className="mt-2">
                    <h4 className="text-xs font-bold uppercase text-slate-500 mb-2 flex items-center gap-1">
                      <ImageIcon size={14} /> Generated Pillow FCC Topic Cards
                    </h4>
                    <div className="grid grid-cols-2 gap-2 max-h-[160px] overflow-y-auto">
                      {active.topics.map(t => (
                        <div key={t.topic_number} className="border rounded p-2 bg-slate-50 flex gap-2 items-center">
                          {t.slide_image && (
                            <img src={t.slide_image} alt={t.title} className="w-16 h-10 object-cover rounded border" />
                          )}
                          <div>
                            <p className="text-xs font-bold line-clamp-1">Section {t.topic_number}: {t.title}</p>
                            <span className="text-[10px] text-slate-500">{t.timestamp_sec}s</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Editing Options Controls */}
              <div className="w-full md:w-[340px] flex flex-col gap-4">
                <label className="flex flex-col gap-1 text-xs font-bold">
                  Editing Prompt Instructions
                  <textarea 
                    className="border rounded p-2 text-xs h-20 resize-none font-normal"
                    value={prompt}
                    onChange={e => setPrompt(e.target.value)}
                  />
                </label>

                <div className="flex flex-col gap-2 border p-3 rounded bg-slate-50">
                  <span className="text-xs font-bold flex items-center gap-1 text-slate-700">
                    <Sliders size={14} /> AI Processing Modules
                  </span>

                  <label className="flex items-center gap-2 text-xs cursor-pointer">
                    <input type="checkbox" checked={removeSilence} onChange={e => setRemoveSilence(e.target.checked)} />
                    <Scissors size={14} className="text-primary" /> Silence Removal (Whisper)
                  </label>

                  <label className="flex items-center gap-2 text-xs cursor-pointer">
                    <input type="checkbox" checked={insertSlides} onChange={e => setInsertSlides(e.target.checked)} />
                    <ImageIcon size={14} className="text-primary" /> FCC Pillow Topic Intro Slides
                  </label>
                </div>

                <Button 
                  onClick={triggerAIProcessing} 
                  disabled={busy} 
                  className="w-full bg-primary hover:bg-red-600 text-white font-bold"
                >
                  {busy ? <LoaderCircle className="animate-spin" /> : <Sparkles />}
                  {busy ? 'Processing Video...' : 'Generate Video'}
                </Button>

                <Button variant="outline" onClick={download} className="w-full flex gap-2 items-center">
                  <Download size={15} /> Download Edited Video
                </Button>

                {editorNotice && <p className="text-xs text-primary font-semibold text-center">{editorNotice}</p>}
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}