using DeskDancer.Characters;
using static DeskDancer.Engine.Ease;

namespace DeskDancer.Engine;

/// <summary>
/// What a mate is doing. <see cref="Act"/> is one of the character's own actions, such as
/// having a drink: played once through, off the beat, with no notes and no dance floor.
/// </summary>
public enum MateState { Idle, Walk, Sit, Sleep, Dance, Act, Drag, Fall }

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
    const double BodyTall = 0.88;      // how much of its height a mate takes up when another runs into it
    const double KnockSpeed = 3.2;     // hit faster than this, in heights per second, a mate is knocked flying
    const double NoticeFrom = 4.5;     // how far off a mate sees another and goes over, in heights

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
    OwnClip _action;
    // An action waits for its pictures before it starts, and is played as drawn (1) or the
    // other way round (-1), whichever leaves it room to go where it goes.
    bool _actionWaiting;
    double _actionWait;
    int _actionSide = 1;
    int _seenSerial = -1, _moveDir = 1;
    double _prevMoveT;
    long _lastNoteBeat = long.MinValue;

    double _walkTarget, _walkPhase;
    double _dragX, _dragY, _swing, _swingV, _vx, _vy;
    readonly List<(double T, double X, double Y)> _samples = [];

    // The other mates: bumping into them, and meeting them.
    double _shove, _dragSpeed, _bumpRest, _mingleRest, _greetIn;
    Gathering? _gathering;
    MateBrain? _visiting;
    int _visitSide;

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
    /// <summary>The other mates on the desktop, if this one is among them. Set by <see cref="Engine.Crowd"/>.</summary>
    public Crowd? Crowd { get; internal set; }
    /// <summary>The get-together this mate is at: saying hello, or dancing.</summary>
    public Gathering? Gathering => _gathering;
    /// <summary>Half the width it takes up when another mate runs into it, in pixels.</summary>
    public double HalfWidth => 0.37 * H * Math.Clamp(_character.AspectRatio, 0.45, 1.15);
    /// <summary>How fast it is moving sideways through the air or in the hand, in pixels a second.</summary>
    public double VelocityX => State == MateState.Fall ? _vx : State == MateState.Drag ? _dragSpeed : 0;
    public bool IsActing => State == MateState.Act;
    /// <summary>The menu name of the action the mate is doing, if it is doing one.</summary>
    public string? CurrentActionName => State == MateState.Act ? _action.Name : null;

    public ICharacter Character
    {
        get => _character;
        set
        {
            _character = value;
            // A clip-based move from the old character means nothing to the new one, and nor
            // does an action, unless the new one has an action by that name too.
            if (_session != null && !ReferenceEquals(_session, _conductor.Session)) StopOwnSession();
            if (State == MateState.Act && !value.ActionClips.Any(a => a.Id == _action.Id)) SetState(MateState.Idle, RandomIdle(), 0.3);
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

    /// <summary>Every dance this mate knows, switched on or not: the character's own clips first, then the built-in moves.</summary>
    public IReadOnlyList<DanceMove> AllMoves() => Moves.ForCharacter(_character, _clock.Bpm);

    /// <summary>
    /// The dances this mate does: its own and the built-in ones, less any that are switched
    /// off. Never empty, because some built-in move is always on.
    /// </summary>
    public IReadOnlyList<DanceMove> AvailableMoves()
    {
        var builtIn = _settings.BuiltInMoves();
        return AllMoves().Where(m => m.Clip == null ? builtIn.Contains(m) : _settings.MoveEnabled(KeyOf(m))).ToList();
    }

    /// <summary>
    /// How a move is named in the settings: a built-in move by its id, the character's own
    /// dance by the character and its clip, as its clips are no one else's.
    /// </summary>
    public string KeyOf(DanceMove move) => Moves.KeyOf(move, _character.Id);

    /// <summary>Every action this mate's character has, switched on or not.</summary>
    public IReadOnlyList<OwnClip> AllActions() => _character.ActionClips;

    /// <summary>The character's actions, less any that are switched off. Often empty.</summary>
    public IReadOnlyList<OwnClip> AvailableActions() => AllActions().Where(a => _settings.MoveEnabled(KeyOf(a))).ToList();

    /// <summary>How an action is named in the settings, by the character and its clip.</summary>
    public string KeyOf(OwnClip action) => Moves.KeyOf(action, _character.Id);

    /// <summary>
    /// Does one of the character's actions: plays its clip once from the start, at its own
    /// speed, and then goes back to standing about. It keeps no beat, so there are no notes
    /// and no dance floor, and a dance party leaves the mate be until it is done. Being
    /// picked up, or told to sit, nap or dance, cuts it short. An action that goes somewhere
    /// takes the mate there, and is played the other way round if that is the way with
    /// room for it. It starts once its pictures have been read, so that none of it is
    /// missed; until then the mate stands as it was. False if the character has no action by
    /// that name.
    /// </summary>
    public bool DoAction(string id)
    {
        var action = AllActions().FirstOrDefault(a => a.Id == id);
        if (action.Id == null) return false;
        StopOwnSession();
        _character.Prepare(action.Id);
        _action = action;
        _awake = 0;
        _actionWaiting = true;
        _actionWait = 0;
        _actionSide = action.Travel is { } travel ? SideWithRoom(travel) : 1;
        SetState(MateState.Act, action.Seconds, 0.25);
        return true;
    }

    /// <summary>How long an action waits for its pictures before it is given up on, in seconds.</summary>
    const double LongestActionWait = 10;

    /// <summary>
    /// Which way round to play an action that travels: as it is showing now (1 as drawn, -1
    /// mirrored) if that keeps it on the screen, and if not, whichever way goes less far off it.
    /// </summary>
    int SideWithRoom(ClipTravel travel)
    {
        int now = Facing * _character.NaturalFacing < 0 ? -1 : 1;
        double lo = Left + EdgeMargin * H, hi = Right - EdgeMargin * H;
        double Over(int side)
        {
            double a = FootX + side * travel.Min * H, b = FootX + side * travel.Max * H;
            return Math.Max(0, lo - Math.Min(a, b)) + Math.Max(0, Math.Max(a, b) - hi);
        }
        return Over(-now) < Over(now) - 1 ? -now : now;
    }

    /// <summary>Does one of the actions that are switched on, picked at random. False if there are none.</summary>
    public bool StartRandomAction()
    {
        var pool = AvailableActions();
        return pool.Count > 0 && DoAction(pool[_rng.Next(pool.Count)].Id);
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
        LeaveGathering(rest: true);
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
        _swing = _swingV = _dragSpeed = 0;
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

        if (_bumpRest > 0) _bumpRest -= dt;
        if (_mingleRest > 0) _mingleRest -= dt;
        if (Crowd is { Mates.Count: > 1 } crowd)
        {
            if (_settings.Collide) Collide(crowd, dt);
            Mingle(crowd);
        }
        else if (_gathering != null)
        {
            LeaveGathering(rest: false);
        }

        bool onFloor = State is MateState.Idle or MateState.Walk or MateState.Sit or MateState.Sleep or MateState.Dance or MateState.Act;
        if (onFloor)
        {
            // Shoved along the floor, it slides a little way and stops.
            if (Math.Abs(_shove) > 0.02 * H)
            {
                _baseX += _shove * dt;
                _shove *= Math.Exp(-7 * dt);
            }
            else
            {
                _shove = 0;
            }

            // The floor can move: gravity toggled, taskbar resized, or dropped on another monitor.
            if (_baseY > Floor) _baseY = Floor;
            else if (_settings.Gravity && _baseY < Floor - 1) Drop();

            // A mate in the middle of an action finishes it before it joins in.
            if (_conductor.PartyOn && _conductor.Session is { } party && !ReferenceEquals(_session, party)
                && State is not (MateState.Fall or MateState.Act))
                BeginSession(party);
        }

        var target = MoveFrame.Neutral;
        string clip = "idle";
        switch (State)
        {
            case MateState.Idle:
                target = IdleFrame();
                if (_gathering is { } gathering) Greet(gathering, ref target, dt);
                else if (_stateTime >= _stateDuration) ChooseNext();
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
            case MateState.Act:
                target = ActFrame(dt, out clip);
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
        // Standing and dancing are what is done at a get-together; anything else is leaving it.
        if (state is not (MateState.Idle or MateState.Dance)) LeaveGathering(rest: true);
        if (state != MateState.Walk) _visiting = null;
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
        // A routine it shares with others, the party's or a get-together's, goes on without it.
        if (_session != null && !ReferenceEquals(_session, _conductor.Session) && !ReferenceEquals(_session, _gathering?.Session))
            _session.Stop();
        _session = null;
    }

    void BeginSession(DanceSession session)
    {
        // Any dance but the get-together's own is a reason to leave it.
        if (!ReferenceEquals(session, _gathering?.Session)) LeaveGathering(rest: true);
        _session = session;
        _seenSerial = -1;
        _awake = 0;
        if (State != MateState.Dance) SetState(MateState.Dance, 0, 0.2);
    }

    void ChooseNext()
    {
        double r = _rng.NextDouble();
        // Sometimes the walk it would have gone on is over to another mate.
        if (_settings.Wander && r < 0.16 && TryVisit()) return;
        if (_settings.Wander && r < 0.45 && TryStartWalk()) return;
        if (_settings.AutoDance && r < 0.63)
        {
            StartRandomDance(1 + _rng.Next(2));
            return;
        }
        // A character with no actions sits down instead, as it always has.
        if (_settings.AutoActions && r is >= 0.63 and < 0.68 && StartRandomAction()) return;
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
        // Walking over to another mate, it heads for wherever that one is now.
        if (_visiting is { } friend)
        {
            if (friend.OpenTo(this)) _walkTarget = ClampX(friend.FootX + _visitSide * MeetingGap(friend));
            else _visiting = null;
        }
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

    MoveFrame ActFrame(double dt, out string clip)
    {
        clip = "idle";
        if (_actionWaiting)
        {
            // Its pictures are still being read: stand as before until they are there. If
            // they cannot be read, or are taking for ever, there is nothing to act out.
            _actionWait += dt;
            var pictures = _character.Readiness(_action.Id);
            if (pictures != ClipReadiness.Ready)
            {
                if (pictures == ClipReadiness.Coming && _actionWait < LongestActionWait) _stateTime = 0;
                else SetState(MateState.Idle, RandomIdle(), 0);
                return IdleFrame();
            }
            _actionWaiting = false;
            StartBlend(0.2);
            // Straight from the first frame, even when it is the same action again.
            _stateTime = 0;
            _clip = _action.Id;
            _clipTime = 0;
        }

        clip = _action.Id;
        if (_stateTime >= _stateDuration)
        {
            // Where it has got to is where it now stands.
            SetState(MateState.Idle, RandomIdle(), 0.3);
            return IdleFrame();
        }

        // The clip has all the motion in it, so the app adds none of its own, bar taking
        // the mate where the action goes.
        var f = MoveFrame.Neutral;
        if (_action.Travel is { } travel)
        {
            f.Body.X = _actionSide * travel.At(_stateTime);
            f.Body.Facing = _actionSide * _character.NaturalFacing;
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
            if (ReferenceEquals(s, _gathering?.Session)) LeaveGathering(rest: true);
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
        bool shared = ReferenceEquals(s, _conductor.Session) || ReferenceEquals(s, _gathering?.Session);
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
        _dragSpeed = Lerp(_dragSpeed, vx, 1 - Math.Exp(-dt * 18));
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

    // ---- The other mates ----

    /// <summary>True for a mate that is staying where it is: not walking by, and not being taken somewhere by a dance or an action.</summary>
    bool Standing => State is MateState.Idle or MateState.Sit or MateState.Sleep
                     || (State == MateState.Dance && _session?.Current.Travels != true);

    /// <summary>
    /// Keeps this mate out of the others. In the air it bounces off whatever it hits, and
    /// what it hits is knocked flying, or shoved if it was hit gently. On the floor it is
    /// pushed along by a mate that is being carried, or batted away by one swung at it, and
    /// two mates standing in the same place step apart. A mate that is walking, or that a
    /// dance or an action is taking somewhere, goes past the others as if behind them.
    /// </summary>
    void Collide(Crowd crowd, double dt)
    {
        if (State == MateState.Drag) return;                  // in the hand, it is the others that give way
        foreach (var other in crowd.Mates)
        {
            if (ReferenceEquals(other, this)) continue;
            // Each is a box standing on its feet. They have collided if the boxes overlap.
            double dx = FootX - other.FootX, overX = HalfWidth + other.HalfWidth - Math.Abs(dx);
            if (overX <= 0) continue;
            double bottom = FootY - Body.Y * H, theirs = other.FootY - other.Body.Y * other.H;
            double overY = Math.Min(bottom, theirs) - Math.Max(bottom - BodyTall * H, theirs - BodyTall * other.H);
            if (overY <= 0) continue;
            int away = dx > 0 ? 1 : dx < 0 ? -1 : crowd.IndexOf(this) < crowd.IndexOf(other) ? -1 : 1;

            if (State == MateState.Fall) Bounce(other, away, overX, overY, bottom, theirs);
            else if (other.State == MateState.Drag) GiveWay(other, away, overX);
            else if (Standing && other.Standing) _baseX += away * Math.Min(overX / 2, 2.2 * H * dt);
        }
    }

    /// <summary>In the air, and into another mate: off it, and it feels the blow.</summary>
    void Bounce(MateBrain other, int away, double overX, double overY, double bottom, double theirs)
    {
        // Coming down on top of it: up off its head, and to one side.
        if (_vy > 0 && overY < overX && bottom < theirs - 0.45 * other.H)
        {
            _baseY -= overY;
            if (_bumpRest > 0) return;
            _bumpRest = 0.12;
            double hard = Math.Abs(_vy) / H;
            _vy = -Math.Max(Math.Abs(_vy) * 0.5, 4.5 * H);
            _vx += away * (1.0 + _rng.NextDouble()) * H;
            other.Squashed(Math.Clamp(hard / 9, 0.4, 1));
            Bonk(FootX, theirs - BodyTall * other.H);
            return;
        }

        _baseX += away * overX;
        double closing = -away * (_vx - other.VelocityX);    // how fast the two are coming together
        if (closing <= 0 || _bumpRest > 0) return;
        _bumpRest = 0.12;
        _vx = other.VelocityX + away * closing * 0.5;
        Bonk(FootX - away * HalfWidth, Math.Min(bottom, theirs) - 0.5 * Math.Min(H, other.H));
        other.Hit(-away * closing);
    }

    /// <summary>On the floor, with a mate that is being carried pushed into this one.</summary>
    void GiveWay(MateBrain other, int away, double overX)
    {
        double swing = other.VelocityX * away;                // how fast it is being swung this way
        if (swing > KnockSpeed * H && _settings.Gravity && _bumpRest <= 0)
        {
            Bonk(FootX - away * HalfWidth, FootY - 0.5 * H);
            Knock(away * swing * 0.6, -(2.2 + Math.Min(swing / H * 0.25, 4)) * H);
            return;
        }
        _baseX += away * overX;
        if (_bumpRest <= 0 && swing > 0.4 * H)
        {
            _bumpRest = 0.5;
            Squashed(0.35);
        }
    }

    /// <summary>
    /// Another mate has run into this one, at so many pixels a second (less than nothing is
    /// from the right). Hit hard, it is knocked flying; hit gently, it is shoved along.
    /// </summary>
    void Hit(double speed)
    {
        _bumpRest = 0.12;
        if (State == MateState.Drag) return;
        if (State == MateState.Fall)
        {
            _vx += speed * 0.5;
            return;
        }
        if (Math.Abs(speed) > KnockSpeed * H && _settings.Gravity)
        {
            Knock(speed * 0.55, -Math.Min(1.5 + Math.Abs(speed) / H * 0.3, 7) * H);
        }
        else
        {
            _shove += speed * 0.45;
            Squashed(0.5);
        }
    }

    /// <summary>Sends the mate flying, as when another is thrown at it. It drops whatever it was doing.</summary>
    public void Knock(double vx, double vy)
    {
        StopOwnSession();
        _awake = 0;
        _swing = _swingV = _shove = 0;
        _bumpRest = 0.15;
        // Clear of the floor, or it would land before it had left.
        _baseY = Math.Min(_baseY, Floor) - 2;
        Drop(vx, Math.Min(vy, -0.5 * H));
    }

    /// <summary>Squashes and springs back, as it does on landing: something has come down on it or bumped it.</summary>
    void Squashed(double strength)
    {
        _impact = strength;
        _landT = 0;
    }

    /// <summary>A few stars where two mates have knocked together.</summary>
    void Bonk(double x, double y)
    {
        if (!_settings.Effects) return;
        for (int i = 0; i < 5; i++)
        {
            double a = _rng.NextDouble() * Tau, v = (0.5 + _rng.NextDouble() * 0.7) * H, life = 0.35 + _rng.NextDouble() * 0.25;
            Particles.Add(new Particle
            {
                Kind = ParticleKind.Star, X = x, Y = y,
                Vx = Math.Cos(a) * v, Vy = Math.Sin(a) * v - 0.3 * H,
                Life = life, MaxLife = life,
                Size = 0.04 + _rng.NextDouble() * 0.035,
                VRot = (_rng.NextDouble() - 0.5) * 8,
                Color = 0xFFFFE27A,
            });
        }
    }

    /// <summary>How far apart two mates stand when they get together, feet to feet, in pixels.</summary>
    double MeetingGap(MateBrain other) => HalfWidth + other.HalfWidth + 0.2 * Math.Max(H, other.H);

    /// <summary>Whether another mate could get together with this one now.</summary>
    bool OpenTo(MateBrain asker)
    {
        // On the same floor: another monitor's can be higher or lower.
        if (Math.Abs(FootY - asker.FootY) > 0.4 * Math.Min(H, asker.H)) return false;
        if (_gathering is { } going) return !going.Over(Beat) && State is MateState.Idle or MateState.Dance;
        return _mingleRest <= 0 && State is MateState.Idle or MateState.Walk or MateState.Sit;
    }

    /// <summary>
    /// Has this mate take notice of the others. One that is right beside it, it gets
    /// together with: they say hello and dance (see <see cref="Engine.Gathering"/>). One
    /// that is a little way off, it walks over to. After a get-together it has had enough
    /// company for a while.
    /// </summary>
    void Mingle(Crowd crowd)
    {
        if (!_settings.Mingle || _conductor.PartyOn)
        {
            // Not wanted; or the party is on, and everyone is dancing already.
            LeaveGathering(rest: false);
            return;
        }
        if (_gathering != null || _mingleRest > 0 || State is not (MateState.Idle or MateState.Walk)) return;

        MateBrain? nearest = null;
        double best = double.MaxValue;
        foreach (var other in crowd.Mates)
        {
            if (ReferenceEquals(other, this) || !other.OpenTo(this)) continue;
            double far = Math.Abs(other.FootX - FootX) - MeetingGap(other);     // further apart than they would stand, by this much
            if (far < best) (best, nearest) = (far, other);
        }
        if (nearest == null) return;

        if (best <= 0.25 * H)
        {
            if (State == MateState.Walk) SetState(MateState.Idle, RandomIdle(), 0.25);
            crowd.Gather(this, nearest);
        }
        else if (State == MateState.Idle && _settings.Wander && _stateTime > 0.8 && best <= NoticeFrom * H)
        {
            Visit(nearest);
        }
    }

    /// <summary>Sets off to see one of the other mates, wherever on the floor it is. False if there is none to see.</summary>
    bool TryVisit()
    {
        if (!_settings.Mingle || _mingleRest > 0 || _conductor.PartyOn || Crowd is not { Mates.Count: > 1 } crowd) return false;
        var open = crowd.Mates.Where(m => !ReferenceEquals(m, this) && m.OpenTo(this)).ToList();
        if (open.Count == 0) return false;
        Visit(open[_rng.Next(open.Count)]);
        return State == MateState.Walk;
    }

    /// <summary>Walks over to stand beside another mate, on the side of it this one is on already.</summary>
    void Visit(MateBrain other)
    {
        int side = FootX >= other.FootX ? 1 : -1;
        double target = ClampX(other.FootX + side * MeetingGap(other));
        if (Math.Abs(target - _baseX) < 0.1 * H) return;      // as near as it can get
        _walkTarget = target;
        _walkPhase = 0;
        SetState(MateState.Walk, 0, 0.2);
        _visiting = other;
        _visitSide = side;
    }

    /// <summary>Called by a <see cref="Engine.Gathering"/> as this mate joins it; <paramref name="place"/> is how many were there first.</summary>
    internal void JoinGathering(Gathering gathering, int place)
    {
        if (!ReferenceEquals(_gathering, gathering)) LeaveGathering(rest: false);
        if (State is MateState.Walk or MateState.Sit) SetState(MateState.Idle, RandomIdle(), 0.3);
        _gathering = gathering;
        _visiting = null;
        _awake = 0;
        // They say hello one after another, not all at once.
        _greetIn = 0.1 + 0.3 * Math.Min(place, 3);
    }

    /// <summary>Leaves the get-together, if it is at one. With <paramref name="rest"/>, it wants no more company for a while.</summary>
    internal void LeaveGathering(bool rest)
    {
        if (_gathering == null) return;
        _gathering.Remove(this);
        _gathering = null;
        if (rest) _mingleRest = 35 + _rng.NextDouble() * 25;
    }

    /// <summary>
    /// At a get-together, before the dancing: turns to the others, says hello with a happy
    /// hop, and starts dancing on the beat the get-together starts on.
    /// </summary>
    void Greet(Gathering gathering, ref MoveFrame f, double dt)
    {
        var friend = gathering.Members.FirstOrDefault(m => !ReferenceEquals(m, this));
        if (friend == null || gathering.Over(Beat))
        {
            // Left on its own there, or it is all over.
            LeaveGathering(rest: friend != null);
            return;
        }

        f.Body.Facing = friend.FootX >= FootX ? 1 : -1;
        f.Limbs.LookX = 0.8 * f.Body.Facing;
        f.Limbs.Face = Face.Happy;
        if (_greetIn >= 0 && (_greetIn -= dt) < 0)
        {
            _pokeT = 0;                                       // the hop it does when it is clicked
            Emit(Fx.Hearts);
        }
        if (Beat >= gathering.StartBeat)
        {
            if (ReferenceEquals(gathering.Members[0], this)) Emit(Fx.Confetti);
            BeginSession(gathering.Session);
        }
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
