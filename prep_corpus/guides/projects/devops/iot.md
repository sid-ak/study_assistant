# IoT

> Part of the Projects guide — [back to index](../README.md)

<a id="iot"></a>

## The situation

Managing the full lifecycle of vehicle IoT devices — from initial provisioning to deployment
rollout. Architecturally complex because of a **nested edge** requirement: parent gateway devices
managing sub-devices within the vehicle, in a hierarchy.

## What you built

You scripted the **entire Azure IoT Edge lifecycle**, end to end:

- **Device Provisioning Service (DPS)** for **zero-touch enrollment** — a device powers on and
  provisions itself against DPS with no manual configuration step.
- **Certificate-based authentication** rather than shared keys, so each device has its own
  cryptographic identity that can be individually revoked. This is the meaningfully harder and
  meaningfully better choice.
- **A nested edge hierarchy** where a parent gateway manages child devices, and deployment manifests
  roll out in a **specific, deterministic order** — parent before children — to prevent sub-device
  "orphaning," where a child ends up managed by a gateway that isn't ready for it yet.

You proactively sought perspectives from the **security and hardware teams** to understand the
physical constraints of operating on a vehicle, rather than designing in isolation.

## Results

- Device onboarding reduced from **hours of manual, error-prone configuration to a single automated
  script.**
- Every vehicle left the facility with a secure, verified software image.

## Why this matters for NetApp

It's your **hardware/software lifecycle** story. It demonstrates you understand that software
doesn't live in a vacuum — it runs on a physical device that must be provisioned, secured, updated,
and eventually decommissioned. NetApp ships appliances. That perspective is directly relevant, and
it's a dimension most pure-software candidates don't have.

The **ordering guarantee** is also a legitimately distributed-systems idea: dependent components
must be updated in a dependency-respecting order or the system passes through an inconsistent
intermediate state. That's the same reasoning behind rolling upgrades in an HA storage pair.

<a id="iotstar"></a>

??? note "STAR"

    **Situation.** We needed to manage the full lifecycle of vehicle IoT devices, and it was
    architecturally complex because of a nested edge requirement — parent gateway devices managing
    sub-devices inside the vehicle, in a hierarchy. At the time, onboarding a device was hours of manual
    configuration, which meant it was both slow and inconsistent.

    **Task.** I took on automating the whole thing end to end, from initial provisioning through
    manifest rollout, and I wanted a genuinely hardened security posture rather than the easy path —
    these are mobile edge devices operating outside a controlled network.

    **Action.** I ramped up on the Azure IoT Edge ecosystem and the Device Provisioning Service, and I
    deliberately went to our security and hardware teams early to understand the physical constraints of
    operating on a vehicle, because I didn't want to design this in isolation. I scripted the full
    lifecycle using certificate-based authentication for zero-touch enrollment — each device gets its
    own cryptographic identity that can be individually revoked, which is meaningfully harder to set up
    than shared keys but the right call for devices in the field. Then I architected the nested
    hierarchy so deployment manifests roll out in a deterministic order, parent gateways before their
    children, which prevents sub-devices from being orphaned against a gateway that isn't ready for
    them.

    **Result.** Device onboarding went from hours of manual, error-prone configuration to a single
    automated script, and every vehicle left the facility with a secure, verified software image. The
    ordering guarantee in particular was the piece I was most careful about, because a
    partially-rolled-out hierarchy is a much worse state to be in than one that hasn't started.

<a id="iotscript"></a>

??? note "Scripts"

    ### ~55s

    > We needed to manage the full lifecycle of IoT devices on vehicles, and the architecture was
    > complicated by a nested edge requirement — parent gateways managing sub-devices in a hierarchy
    > inside each vehicle. At the time, onboarding was hours of manual configuration per device, so it
    > was slow and, more importantly, inconsistent.
    >
    > I took on automating it end to end. I ramped up on Azure IoT Edge and the Device Provisioning
    > Service, and I made a point of going to our security and hardware teams first, because these are
    > devices operating in the field outside a controlled network and I didn't want to design that in
    > isolation.
    >
    > Two decisions I'd highlight. I used certificate-based authentication rather than shared keys for
    > zero-touch enrollment — it's more work to set up, but each device gets its own cryptographic
    > identity that can be revoked individually, which is what you want for hardware you can't
    > physically reach. And I architected the nested hierarchy so deployment manifests roll out in a
    > deterministic order, parents before children, because if a child device provisions against a
    > gateway that isn't ready, it's orphaned — and a partially-deployed hierarchy is a worse state than
    > one that hasn't started.
    >
    > Onboarding went from hours of manual config to a single script, and every vehicle shipped with a
    > verified, secure image.

<a id="iotqa"></a>

??? note "QA"

    **Q: Why certificate-based auth over shared access keys?**

    > Individual identity and individual revocation. With a shared key, compromising one device
    > compromises everything sharing that key, and rotating it means touching every device. With
    > per-device certificates, each device has its own identity, you can revoke exactly one, and you get
    > a real chain of trust back to your CA. It's more infrastructure — you need a CA, an issuance
    > process, and a renewal story — but for hardware operating in the field where physical access is
    > plausible, it's the only defensible answer.

    **Q: What is a nested edge and why does it complicate things?**

    > A parent gateway device sits between child devices and the cloud, so the children never talk to
    > the cloud directly — they talk to the parent, which relays. That's often necessary because the
    > children are on an isolated network segment or lack the connectivity for a direct cloud link. The
    > complication is that it creates a **dependency order**. The parent has to exist, be provisioned,
    > and be reachable before any child can provision through it. So deployment isn't a set of
    > independent operations, it's an ordered graph — and if you roll out in the wrong order, children
    > fail to register and end up orphaned.

    **Q: How did you ensure the ordering was actually respected?**

    > The rollout was scripted to explicitly deploy and confirm the parent's manifest before initiating
    > any child's, rather than firing them in parallel and hoping. The general principle is that you
    > can't treat a dependency graph as a flat list — the same reason you can't start a service before
    > its database. What I'd add if I were extending it is a verification step between stages, so the
    > script confirms the parent is actually healthy and accepting connections rather than just
    > confirming the deployment call returned.

    **Q: How does this relate to storage systems?**

    > The ordering problem is the same problem as a rolling upgrade in an HA pair. You have components
    > with a dependency relationship, you can't take them all down at once, and there's an intermediate
    > state where they're running different versions and still have to interoperate. The discipline is
    > identical: deploy in dependency order, verify health between stages, and design so that the
    > intermediate state is a valid state rather than something you race through. And more broadly, the
    > appliance lifecycle framing — provision, secure, update, decommission hardware you can't
    > physically reach — is directly what shipping a storage appliance involves.
