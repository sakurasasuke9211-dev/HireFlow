-- Private bucket for JD and resume originals. The API uses the service role.

INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('hireflow', 'hireflow', false, 10485760)
ON CONFLICT (id) DO NOTHING;
