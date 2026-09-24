function value = x280FileSHA256(fileName)
%X280FILESHA256 Stream a file digest for generation and artifact provenance.
arguments
    fileName (1,1) string {mustBeFile}
end
file = fopen(fileName, 'rb');
assert(file >= 0, 'x280linux:HashOpen', 'Cannot read %s.', fileName);
closeFile = onCleanup(@() fclose(file));
digest = java.security.MessageDigest.getInstance('SHA-256');
while ~feof(file)
    digest.update(fread(file, 1024 * 1024, '*uint8'));
end
bytes = uint8(mod(double(digest.digest), 256));
value = lower(string(reshape(dec2hex(bytes, 2).', 1, [])));
end
