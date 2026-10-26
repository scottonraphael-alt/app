import { resolveAvatarUrl } from "./avatar";

it("résout les copies sur le domaine backend et conserve les URL Discord", () => {
  const previous = process.env.REACT_APP_BACKEND_URL;
  process.env.REACT_APP_BACKEND_URL = "https://api.loasis.app/";
  try {
    expect(resolveAvatarUrl('/api/tickets/avatars/key')).toBe('https://api.loasis.app/api/tickets/avatars/key');
    expect(resolveAvatarUrl('https://cdn.discordapp.com/avatar.png')).toBe('https://cdn.discordapp.com/avatar.png');
    expect(resolveAvatarUrl(null)).toBe('');
  } finally {
    if (previous === undefined) delete process.env.REACT_APP_BACKEND_URL;
    else process.env.REACT_APP_BACKEND_URL = previous;
  }
});
