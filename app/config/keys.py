from Crypto.PublicKey import RSA

key = RSA.generate(4096)
private_key = key.exportKey()
public_key = key.publickey().exportKey()

with open("private.key", "wb") as f:
    f.write(private_key)

with open("public.key", "wb") as f:
    f.write(public_key)
