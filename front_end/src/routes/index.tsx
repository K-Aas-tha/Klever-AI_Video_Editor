import { createFileRoute } from "@tanstack/react-router";
import { VideoWorkspace } from '@/components/video-workspace';

export const Route = createFileRoute("/")({
  head: () => ({ meta: [
    { title: 'Klever — Create Your Next Standout Clip' },
    { name: 'description', content: 'Your creative video workspace. Upload videos, preview short-form clips, and make your next story stand out with Klever.' },
    { property: 'og:title', content: 'Klever — Create Your Next Standout Clip' },
    { property: 'og:description', content: 'A little less editing, a little more creating. Your creative workspace for short-form video.' },
    { property: 'og:type', content: 'website' },
    { name: 'twitter:card', content: 'summary_large_image' },
  ] }),
  component: VideoWorkspace,
});
