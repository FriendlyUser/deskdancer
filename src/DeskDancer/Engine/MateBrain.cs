using DeskDancer.Characters;
using static DeskDancer.Engine.Ease;

namespace DeskDancer.Engine;

public enum MateState { Idle, Walk, Sit, Sleep, Dance, Drag, Fall }

/// <summary>
/// Decides what one mate is doing and where it is. Knows nothing about windows or
/// drawing: it takes the usable screen area in pixels and produces a foot position,
/// a pose and some particles each frame.
/// </summary>
public sealed class MateBrain
{
    const double WalkSpeed = 0.55;     // character heights per second
    const double GravityAccel = 15;    // character heights per second squared
    const double EdgeMargin = 0.42;    // how close the feet may get to a screen edge, in heights

    readonly BeatClock _clock;
    readonly Conductor _conductor;
    readonly Settings _settings;
    readonly Random _rng;
    ICharacter _character;

    double _baseX, _baseY;
    double _time, _stateTime, _stateDuration, _clipTime, _awake;
    string _clip = "idle";

    MoveFrame _last = MoveFrame.Neutral, _blendFrom = MoveFrame.Neutral;
    double _blendT = 1, _blendDur;

    DanceSession? _session;
    int _seenSerial = -1, _moveDir = 1;
    double _prevMoveT;
    long _lastNoteBeat = long.MinValue;

    double _walkTarget, _walkPhase;
    double _dragX, _dragY, _swing, _swingV, _vx, _vy;
    readonly List<(double T, double X, double Y)> _samples = [];

    double _landT = 10, _impact, _pokeT = 10, _blinkIn = 2, _blinkT, _zzzIn;
    bool _hover;
    double _lookX, _lookY;
    double _prevFootX, _trailV;

    public MateBrain(BeatClock clock, Conductor conductor, Settings settings, ICharacter character, Random? rng = null)
    {
        _clock = clock;
        _conductor = conductor;
        _settings = settings;
        _character = character;
        _rng = rng ?? new Random();
        _stateDuration = 2;
    }

    // ---- World, in screen pixels. The window refreshes these before every update. ----

    /// <summary>Character height in pixels.</summary>
    public double H { get; set; } = 150;
    public double Left { get; set; }
    public double Right { get; set; } = 1920;
    public double Top { get; set; }
    public double Floor { get; set; } = 1080;

    // ---- Output ----

    public double FootX { get; private set; }
    public double FootY { get; private set; }
    public MateState State { get; private set; }
    public BodyPose Body { get; private set; } = BodyPose.Identity;
    public LimbPose Limbs { get; private set; } = LimbPose.Rest;
    public int Facing { get; private set; } = 1;
    public string Clip => _clip;
    public double ClipTime => _clipTime;
    public double Time => _time;
    public double Beat { get; private set; }
    /// <summary>Eases between 0 (resting) and 1 (dancing).</summary>
    public double Energy { get; private set; }
    /// <summary>Angle in degrees that loose parts trail behind the body.</summary>
    public double Trail { get; private set; }
    public ParticleSystem Particles { get; } = new();
    public bool IsDancing => State == MateState.Dance;
    public string? CurrentMoveName => State == MateState.Dance ? _session?.Current.Name : null;

    public ICharacter Character
    {
        get => _character;
        set
        {
            _character = value;
            // A clip-based move from the old character means nothing to the new one.
            if (_session != null && !ReferenceEquals(_session, _conductor.Session)) StopOwnSession();
        }
    }

    public void Place(double footX, double footY)
    {
        _baseX = FootX = _prevFootX = footX;
        _baseY = FootY = footY;
    }

    /// <summary>Lets go of the mate in mid-air so it falls to the floor.</summary>
    public void Drop(double vx = 0, double vy = 0)
    {
        _vx = vx;
        _vy = vy;
        // A new mate drops in before its first frame is drawn, so this is early notice.
        _character.Prepare("fall");
        SetState(MateState.Fall, 0, 0.1);
    }

    // ---- Commands ----

    /// <summary>Every dance this mate can do right now: the character's own clips first, then the built-in moves.</summary>
    public IReadOnlyList<DanceMove> AvailableMoves()
    {
        var list = new List<DanceMove>();
        foreach (var clip in _character.DanceClips)
        {
            double beats = Math.Max(0.25, clip.Seconds * _clock.Bpm / 60);
            double total = beats;
            while (total < 4) total += beats;
            list.Add(Moves.FromClip(clip.Id, clip.Name, total));
        }
        list.AddRange(Moves.All);
        return list;
    }

    public void StartDance(IEnumerable<DanceMove> moves)
    {
        var list = moves.ToList();
        // The later moves are still beats away: time for their pictures to be fetched.
        foreach (var move in list) _character.Prepare(move.Clip ?? "dance");
        var session = DanceSession.FromList(_clock.Beat, list);
        if (session != null) BeginSession(session);
    }

    public void StartRandomDance(int count = 4, bool allowTravel = true)
    {
        var pool = AvailableMoves().Where(m => allowTravel || !m.Travels).ToList();
        var picks = new List<DanceMove>();
        while (picks.Count < count && pool.Count > 0)
        {
            var pick = pool[_rng.Next(pool.Count)];
            pool.Remove(pick);
            picks.Add(pick);
        }
        StartDance(picks);
    }

    public void StopDance()
    {
        if (State != MateState.Dance) return;
        StopOwnSession();
        SetState(MateState.Idle, RandomIdle(), 0.3);
    }

    public void Sit()
    {
        StopOwnSession();
        SetState(MateState.Sit, 6 + _rng.NextDouble() * 8, 0.35);
    }

    public void Sleep()
    {
        StopOwnSession();
        _zzzIn = 0.8;
        SetState(MateState.Sleep, 25 + _rng.NextDouble() * 30, 0.5);
    }

    public void Wake()
    {
        _awake = 0;
        SetState(MateState.Idle, RandomIdle(), 0.3);
    }

    public void BeginDrag()
    {
        StopOwnSession();
        _dragX = FootX;
        _dragY = FootY;
        _swing = _swingV = 0;
        _samples.Clear();
        // What is carried is dropped sooner or later.
        _character.Prepare("fall");
        SetState(MateState.Drag, 0, 0.12);
    }

    public void DragTo(double footX, double footY)
    {
        _dragX = footX;
        _dragY = footY;
    }

    public void EndDrag()
    {
        if (State != MateState.Drag) return;
        double vx = 0, vy = 0;
        if (_samples.Count >= 2)
        {
            var a = _samples[0];
            var b = _samples[^1];
            double span = b.T - a.T;
            if (span > 0.015)
            {
                vx = (b.X - a.X) / span;
                vy = (b.Y - a.Y) / span;
            }
        }
        double limit = 26 * H;
        vx = Math.Clamp(vx, -limit, limit);
        vy = Math.Clamp(vy, -limit, limit);
        _awake = 0;

        if (!_settings.Gravity || _baseY >= Floor - 1)
        {
            if (_baseY > Floor) _baseY = Floor;
            _impact = 0.35;
            _landT = 0;
            SetState(MateState.Idle, RandomIdle(), 0.2);
        }
        else
        {
            Drop(vx, vy);
        }
    }

    /// <summary>A single click: a happy little hop.</summary>
    public void Poke()
    {
        _pokeT = 0;
        Emit(Fx.Hearts);
        if (State == MateState.Sleep) Wake();
        else if (State == MateState.Sit) SetState(MateState.Idle, RandomIdle(), 0.3);
    }

    public void SetHover(bool hover, double lookX = 0, double lookY = 0)
    {
        _hover = hover;
        _lookX = Math.Clamp(lookX, -1, 1);
        _lookY = Math.Clamp(lookY, -1, 1);
    }

    // ---- Simulation ----

    public void Update(double dt)
    {
        dt = Math.Clamp(dt, 0, 0.1);
        _time += dt;
        _stateTime += dt;
        _clipTime += dt;
        _awake += dt;
        Beat = _clock.Beat;

        bool onFloor = State is MateState.Idle or MateState.Walk or MateState.Sit or MateState.Sleep or MateState.Dance;
        if (onFloor)
        {
            // The floor can move: gravity toggled, taskbar resized, or dropped on another monitor.
            if (_baseY > Floor) _baseY = Floor;
            else if (_settings.Gravity && _baseY < Floor - 1) Drop();

            if (_conductor.PartyOn && _conductor.Session is { } party && !ReferenceEquals(_session, party) && State != MateState.Fall)
                BeginSession(party);
        }

        var target = MoveFrame.Neutral;
        string clip = "idle";
        switch (State)
        {
            case MateState.Idle:
                target = IdleFrame();
                if (_stateTime >= _stateDuration) ChooseNext();
                break;
            case MateState.Walk:
                target = WalkFrame(dt);
                clip = "walk";
                break;
            case MateState.Sit:
                target = SitFrame();
                clip = "sit";
                if (_stateTime >= _stateDuration) SetState(MateState.Idle, RandomIdle(), 0.35);
                break;
            case MateState.Sleep:
                target = SleepFrame(dt);
                clip = "sleep";
                if (_stateTime >= _stateDuration) Wake();
                break;
            case MateState.Dance:
                target = DanceFrame(out clip);
                break;
            case MateState.Drag:
                target = DragFrame(dt);
                clip = "drag";
                break;
            case MateState.Fall:
                target = FallFrame(dt);
                clip = "fall";
                break;
        }

        if (clip != _clip)
        {
            _clip = clip;
            _clipTime = 0;
        }

        MoveFrame frame;
        if (_blendT < _blendDur)
        {
            _blendT += dt;
            frame = MoveFrame.Lerp(_blendFrom, target, InOut(_blendT / _blendDur));
        }
        else
        {
            frame = target;
        }
        _last = frame;

        // Short-lived reactions layered on top of whatever the state is doing.
        if (_landT < 1.2)
        {
            _landT += dt;
            frame.Body.Squash(0.24 * _impact * Decay(_landT, 7) * Math.Cos(_landT * 13));
        }
        if (_pokeT < 0.9)
        {
            _pokeT += dt;
            double hop = Arc(_pokeT / 0.38);
            frame.Body.Y += 0.14 * hop;
            frame.Body.Squash(-0.05 * hop + 0.10 * Decay(_pokeT - 0.38, 9) * (_pokeT > 0.38 ? 1 : 0));
            if (State != MateState.Sleep) frame.Limbs.Face = Face.Love;
        }

        _blinkIn -= dt;
        if (_blinkIn <= 0)
        {
            _blinkT = 0.13;
            _blinkIn = 2.4 + _rng.NextDouble() * 3.2;
        }
        if (_blinkT > 0)
        {
            _blinkT -= dt;
            frame.Limbs.EyeOpen = Math.Min(frame.Limbs.EyeOpen, 0.08);
        }

        if (frame.Body.Facing != 0) Facing = frame.Body.Facing;
        Body = frame.Body;
        Limbs = frame.Limbs;

        double x = _baseX + frame.Body.X * H;
        if (State != MateState.Drag) x = ClampX(x);
        FootX = x;
        FootY = _baseY;

        // Loose parts lag behind sideways movement, on a soft spring.
        double speed = dt > 0 ? (FootX - _prevFootX) / dt / H : 0;
        _prevFootX = FootX;
        double trailTarget = Math.Clamp(-speed * 16 - frame.Body.Lean * 0.6, -55, 55);
        _trailV += ((trailTarget - Trail) * 70 - _trailV * 9) * dt;
        Trail = Math.Clamp(Trail + _trailV * dt, -70, 70);

        Energy = Lerp(Energy, State == MateState.Dance ? 1 : 0, 1 - Math.Exp(-dt * 5));

        if (State == MateState.Dance && _settings.Effects)
        {
            long whole = (long)Math.Floor(Beat);
            if (whole != _lastNoteBeat)
            {
                _lastNoteBeat = whole;
                EmitNote(whole % 2 == 0 ? 1 : -1);
            }
        }

        Particles.Update(dt);
    }

    double ClampX(double x)
    {
        double lo = Left + EdgeMargin * H, hi = Right - EdgeMargin * H;
        return hi > lo ? Math.Clamp(x, lo, hi) : (Left + Right) / 2;
    }

    double RandomIdle() => 2.5 + _rng.NextDouble() * 5;

    void SetState(MateState state, double duration, double blend)
    {
        StartBlend(blend);
        // Leaving the dance floor always drops the session, so a party can pull the mate back in later.
        if (state != MateState.Dance) _session = null;
        State = state;
        _stateTime = 0;
        _stateDuration = duration;
    }

    /// <summary>Freezes the current pose as the start of a cross-fade and makes "here" the new origin.</summary>
    void StartBlend(double seconds)
    {
        _baseX = FootX;
        _blendFrom = _last;
        _blendFrom.Body = _last.Body.Settled();
        _blendT = 0;
        _blendDur = seconds;
    }

    void StopOwnSession()
    {
        if (_session != null && !ReferenceEquals(_session, _conductor.Session)) _session.Stop();
        _session = null;
    }

    void BeginSession(DanceSession session)
    {
        _session = session;
        _seenSerial = -1;
        _awake = 0;
        if (State != MateState.Dance) SetState(MateState.Dance, 0, 0.2);
    }

    void ChooseNext()
    {
        double r = _rng.NextDouble();
        if (_settings.Wander && r < 0.45 && TryStartWalk()) return;
        if (_settings.AutoDance && r < 0.63)
        {
            StartRandomDance(1 + _rng.Next(2));
            return;
        }
        if (r < 0.78) Sit();
        else if (r < 0.86 && _awake > 120) Sleep();
        else SetState(MateState.Idle, RandomIdle(), 0);
    }

    bool TryStartWalk()
    {
        double lo = Left + EdgeMargin * H, hi = Right - EdgeMargin * H;
        if (hi - lo < H) return false;
        double target = lo + _rng.NextDouble() * (hi - lo);
        if (Math.Abs(target - _baseX) < 0.8 * H) return false;
        _walkTarget = target;
        _walkPhase = 0;
        SetState(MateState.Walk, 0, 0.2);
        return true;
    }

    void ApplyHover(ref MoveFrame f)
    {
        if (!_hover) return;
        f.Limbs.Face = Face.Happy;
        f.Limbs.LookX = _lookX;
        f.Limbs.LookY = _lookY;
    }

    MoveFrame IdleFrame()
    {
        var f = MoveFrame.Neutral;
        double breath = Math.Sin(_time * 1.9);
        f.Body.Squash(0.012 * breath);
        f.Limbs.ArmL = f.Limbs.ArmR = 12 + 2.5 * breath;
        f.Limbs.HeadTilt = 5 * Math.Sin(_time * 0.43) * Math.Sin(_time * 0.17);
        f.Limbs.HeadBob = 0.004 * breath;
        f.Limbs.LookX = 0.6 * Math.Sin(_time * 0.31) * Math.Sin(_time * 0.11);
        ApplyHover(ref f);
        return f;
    }

    MoveFrame WalkFrame(double dt)
    {
        double dx = _walkTarget - _baseX;
        int d = dx >= 0 ? 1 : -1;
        double step = WalkSpeed * H * dt;
        if (Math.Abs(dx) <= step)
        {
            _baseX = _walkTarget;
            FootX = ClampX(_baseX);
            SetState(MateState.Idle, RandomIdle(), 0.25);
            return IdleFrame();
        }

        _baseX += d * step;
        _walkPhase += dt * 1.9;
        double s = Math.Sin(_walkPhase * Tau);

        var f = MoveFrame.Neutral;
        f.Body.Facing = d;
        if (_character.IsRigged)
        {
            f.Body.Y = 0.025 * Math.Abs(s);
            f.Body.Lean = d * 3;
            f.Limbs.LegL = 3 + 10 * Math.Max(0, s); f.Limbs.LiftL = 0.5 * Math.Max(0, s);
            f.Limbs.LegR = 3 + 10 * Math.Max(0, -s); f.Limbs.LiftR = 0.5 * Math.Max(0, -s);
            f.Limbs.ArmL = 16 + 14 * s; f.Limbs.ArmR = 16 - 14 * s;
            f.Limbs.ElbowL = f.Limbs.ElbowR = 28;
            f.Limbs.HeadTilt = 3 * s;
            f.Limbs.LookX = d * 0.7;
        }
        else if (!_character.HasClip("walk"))
        {
            // No walk animation supplied: waddle the still image instead.
            f.Body.Lean = 6 * s;
            f.Body.Y = 0.035 * Math.Abs(s);
            f.Body.Squash(0.03 * Math.Cos(_walkPhase * 2 * Tau));
        }
        return f;
    }

    MoveFrame SitFrame()
    {
        var f = MoveFrame.Neutral;
        double breath = Math.Sin(_time * 1.7);
        f.Limbs.Crouch = 1;
        f.Limbs.LegL = f.Limbs.LegR = 68;
        f.Limbs.ArmL = f.Limbs.ArmR = 28;
        f.Limbs.ElbowL = f.Limbs.ElbowR = -40;
        f.Limbs.HeadTilt = 4 * Math.Sin(_time * 0.6);
        bool fake = !_character.IsRigged && !_character.HasClip("sit");
        f.Body.Squash(0.012 * breath + (fake ? 0.10 : 0));
        ApplyHover(ref f);
        return f;
    }

    MoveFrame SleepFrame(double dt)
    {
        var f = MoveFrame.Neutral;
        double breath = Math.Sin(_time * 1.1);
        bool fake = !_character.IsRigged && !_character.HasClip("sleep");
        f.Limbs.Crouch = 1;
        f.Limbs.LegL = f.Limbs.LegR = 68;
        f.Limbs.ArmL = f.Limbs.ArmR = 20;
        f.Limbs.ElbowL = f.Limbs.ElbowR = -20;
        f.Limbs.HeadTilt = 13 + 2 * breath;
        f.Limbs.HeadBob = -0.02;
        f.Limbs.EyeOpen = 0;
        f.Limbs.Face = Face.Sleepy;
        f.Body.Squash(0.02 * breath + (fake ? 0.14 : 0));
        if (fake) f.Body.Lean = 7;

        _zzzIn -= dt;
        if (_zzzIn <= 0 && _settings.Effects)
        {
            _zzzIn = 1.5;
            Particles.Add(new Particle
            {
                Kind = ParticleKind.Zzz,
                X = FootX + 0.22 * H, Y = FootY - 0.75 * H,
                Vx = 0.10 * H, Vy = -0.22 * H,
                Life = 2.4, MaxLife = 2.4, Size = 0.07, Color = 0xFFB9C4FF,
                Wobble = _rng.NextDouble() * Tau,
            });
        }
        return f;
    }

    MoveFrame DanceFrame(out string clip)
    {
        clip = "idle";
        var s = _session;
        if (s == null)
        {
            SetState(MateState.Idle, RandomIdle(), 0.3);
            return _last;
        }

        s.Update(Beat);
        if (s.Finished)
        {
            _session = null;
            SetState(MateState.Idle, RandomIdle(), 0.3);
            return _last;
        }

        double t = Beat - s.StartBeat;
        if (s.Serial != _seenSerial)
        {
            _seenSerial = s.Serial;
            StartBlend(Math.Min(0.3, 0.35 * 60 / _clock.Bpm));
            _moveDir = PickDirection(s);
            _prevMoveT = t - 1e-6;
        }

        var f = s.Current.Eval(t, _moveDir);
        if (_settings.Effects)
        {
            foreach (var (beat, kind) in s.Current.Effects)
                if (beat > _prevMoveT && beat <= t) Emit(kind);
        }
        _prevMoveT = t;
        clip = s.Current.Clip ?? "dance";
        return f;
    }

    /// <summary>Travelling moves head towards whichever side has room for them.</summary>
    int PickDirection(DanceSession s)
    {
        double roomRight = Right - EdgeMargin * H - FootX, roomLeft = FootX - Left - EdgeMargin * H;
        bool shared = ReferenceEquals(s, _conductor.Session);
        int preferred = shared ? s.Dir : roomRight >= roomLeft ? 1 : -1;
        if (!s.Current.Travels) return preferred;

        double need = Math.Abs(s.Current.NetTravel(1)) * H;
        double Room(int d) => d > 0 ? roomRight : roomLeft;
        if (Room(preferred) >= need) return preferred;
        if (Room(-preferred) >= need) return -preferred;
        return roomRight >= roomLeft ? 1 : -1;
    }

    MoveFrame DragFrame(double dt)
    {
        double vx = dt > 0 ? (_dragX - _baseX) / dt : 0;
        _baseX = _dragX;
        _baseY = _dragY;
        _samples.Add((_time, _dragX, _dragY));
        while (_samples.Count > 2 && _time - _samples[0].T > 0.12) _samples.RemoveAt(0);

        // Held by the scruff, the feet swing out behind the direction of travel.
        double target = Math.Clamp(vx / H * 9, -40, 40);
        _swingV += ((target - _swing) * 90 - _swingV * 9) * dt;
        _swing = Math.Clamp(_swing + _swingV * dt, -60, 60);

        var f = MoveFrame.Neutral;
        f.Body.Spin = _swing;
        f.Body.Squash(-0.04);
        f.Limbs.ArmL = f.Limbs.ArmR = 26 + Math.Abs(_swing) * 0.4;
        f.Limbs.LegL = 6 - _swing * 0.3;
        f.Limbs.LegR = 6 + _swing * 0.3;
        f.Limbs.LiftL = f.Limbs.LiftR = 0.15;
        f.Limbs.HeadTilt = -_swing * 0.3;
        f.Limbs.Face = Face.Wide;
        return f;
    }

    MoveFrame FallFrame(double dt)
    {
        _vy += GravityAccel * H * dt;
        _vx *= Math.Exp(-0.4 * dt);
        _baseX += _vx * dt;
        _baseY += _vy * dt;

        double lo = Left + EdgeMargin * H, hi = Right - EdgeMargin * H;
        if (hi > lo)
        {
            if (_baseX < lo) { _baseX = lo; _vx = Math.Abs(_vx) * 0.55; }
            else if (_baseX > hi) { _baseX = hi; _vx = -Math.Abs(_vx) * 0.55; }
        }
        if (_baseY < Top + H && _vy < 0)
        {
            _baseY = Top + H;
            _vy = Math.Abs(_vy) * 0.3;
        }

        double spinTarget = Math.Clamp(_vx / H * 6, -35, 35);
        _swingV += ((spinTarget - _swing) * 60 - _swingV * 8) * dt;
        _swing += _swingV * dt;

        var f = MoveFrame.Neutral;
        f.Body.Spin = _swing;
        f.Body.Squash(-0.05);
        f.Limbs.ArmL = 150 + 20 * Math.Sin(_time * 18);
        f.Limbs.ArmR = 150 + 20 * Math.Sin(_time * 18 + 2);
        f.Limbs.LegL = 10 + 10 * Math.Sin(_time * 14);
        f.Limbs.LegR = 10 + 10 * Math.Sin(_time * 14 + 3);
        f.Limbs.Face = Face.Wide;

        if (_baseY >= Floor)
        {
            _baseY = Floor;
            if (_vy > 5.5 * H)
            {
                // A hard landing gets one bounce.
                _vy = -_vy * 0.36;
                _vx *= 0.7;
                Emit(Fx.Stomp);
            }
            else
            {
                _impact = Math.Clamp(_vy / (6 * H), 0.3, 1);
                _landT = 0;
                _vx = _vy = 0;
                Emit(Fx.Stomp);
                SetState(MateState.Idle, 1.2 + _rng.NextDouble() * 2, 0.18);
            }
        }
        return f;
    }

    // ---- Effects ----

    uint RandomNeon() => ParticleSystem.Neon[_rng.Next(ParticleSystem.Neon.Length)];

    void EmitNote(int side)
    {
        Particles.Add(new Particle
        {
            Kind = ParticleKind.Note,
            X = FootX + side * (0.30 + _rng.NextDouble() * 0.12) * H,
            Y = FootY - (0.72 + Body.Y + _rng.NextDouble() * 0.15) * H,
            Vx = side * (0.10 + _rng.NextDouble() * 0.18) * H,
            Vy = -(0.42 + _rng.NextDouble() * 0.2) * H,
            Life = 1.5, MaxLife = 1.5,
            Size = 0.075 + _rng.NextDouble() * 0.03,
            Rot = (_rng.NextDouble() - 0.5) * 0.5,
            Color = RandomNeon(),
            Wobble = _rng.NextDouble() * Tau,
        });
    }

    void Emit(Fx kind)
    {
        if (!_settings.Effects) return;
        double cx = FootX, cy = FootY - (Body.Y + 0.5) * H;
        switch (kind)
        {
            case Fx.Sparkle:
                for (int i = 0; i < 8; i++)
                {
                    double a = _rng.NextDouble() * Tau, v = (0.5 + _rng.NextDouble() * 0.8) * H;
                    double life = 0.5 + _rng.NextDouble() * 0.35;
                    Particles.Add(new Particle
                    {
                        Kind = ParticleKind.Star,
                        X = cx + Math.Cos(a) * 0.28 * H, Y = cy + Math.Sin(a) * 0.34 * H,
                        Vx = Math.Cos(a) * v, Vy = Math.Sin(a) * v,
                        Life = life, MaxLife = life,
                        Size = 0.045 + _rng.NextDouble() * 0.05,
                        VRot = (_rng.NextDouble() - 0.5) * 6,
                        Color = RandomNeon(),
                    });
                }
                break;

            case Fx.Confetti:
                for (int i = 0; i < 28; i++)
                {
                    double life = 1.2 + _rng.NextDouble() * 0.8;
                    Particles.Add(new Particle
                    {
                        Kind = ParticleKind.Confetti,
                        X = cx + (_rng.NextDouble() - 0.5) * 0.4 * H, Y = FootY - 0.15 * H,
                        Vx = (_rng.NextDouble() - 0.5) * 2.6 * H,
                        Vy = -(1.8 + _rng.NextDouble() * 1.9) * H,
                        Gravity = 4.2 * H,
                        Life = life, MaxLife = life,
                        Size = 0.035 + _rng.NextDouble() * 0.03,
                        Rot = _rng.NextDouble() * Tau, VRot = (_rng.NextDouble() - 0.5) * 22,
                        Color = RandomNeon(),
                    });
                }
                break;

            case Fx.Stomp:
                Particles.Add(new Particle
                {
                    Kind = ParticleKind.Ring, X = cx, Y = FootY,
                    Life = 0.45, MaxLife = 0.45, Size = 0.22, Color = 0xFFFFFFFF,
                });
                break;

            case Fx.Hearts:
                for (int i = 0; i < 3; i++)
                {
                    double life = 1.0 + _rng.NextDouble() * 0.5;
                    Particles.Add(new Particle
                    {
                        Kind = ParticleKind.Heart,
                        X = cx + (_rng.NextDouble() - 0.5) * 0.5 * H, Y = FootY - (0.85 + _rng.NextDouble() * 0.1) * H,
                        Vx = (_rng.NextDouble() - 0.5) * 0.25 * H, Vy = -(0.35 + _rng.NextDouble() * 0.25) * H,
                        Life = life, MaxLife = life,
                        Size = 0.06 + _rng.NextDouble() * 0.03,
                        Color = 0xFFFF6B9D,
                        Wobble = _rng.NextDouble() * Tau,
                    });
                }
                break;
        }
    }
}
