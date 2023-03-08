package frc.robot.commands.Arm.sequences;

// Copyright (c) FIRST and other WPILib contributors.
// Open Source Software; you can modify and/or share it under the terms of
// the WPILib BSD license file in the root directory of this project.



import com.revrobotics.CANSparkMax.IdleMode;

import edu.wpi.first.wpilibj2.command.CommandBase;
import frc.robot.commands.Arm.presets.ArmToPresetNoTurret;
import frc.robot.commands.Arm.presets.ElbowExtendPreset;
import frc.robot.subsystems.Arm;
import frc.robot.subsystems.Drive;
import frc.robot.testingdashboard.TestingDashboard;

public class ConeHighPostCenterState extends CommandBase {
  enum State {
    INIT,
    SCHEDULE_EXTEND_ELBOW,
    EXTEND_ELBOW,
    SCHEDULE_EXTEND_SHOULDER,
    EXTEND_SHOULDER,
    DONE
  }

  ElbowExtendPreset m_extendElbow = new ElbowExtendPreset(-133);
  ArmToPresetNoTurret m_extendArm = new ArmToPresetNoTurret(42, -113, -144);

  private boolean m_isFinished;
  private State m_state;
  /** Creates a new ReachForNextBarStatefully. */
  public ConeHighPostCenterState() {
    // Use addRequirements() here to declare subsystem dependencies.
    

    m_state = State.INIT;
    m_isFinished = false;
  }

  //Register with TestingDashboard
  public static void registerWithTestingDashboard() {
    Arm climber = Arm.getInstance();
    ConeHighPostCenterState cmd = new ConeHighPostCenterState();
    TestingDashboard.getInstance().registerCommand(climber, "TestCommands", cmd);
  }

  // Called when the command is initially scheduled.
  @Override
  public void initialize() {
    m_state = State.INIT;
    m_isFinished = false;
  }

  // Called every time the scheduler runs while the command is scheduled.
  @Override
  public void execute() {
    switch (m_state) {
      case INIT:
        m_state = State.SCHEDULE_EXTEND_ELBOW;
        break;
      case SCHEDULE_EXTEND_ELBOW:
        m_extendElbow.schedule();
        m_state = State.EXTEND_ELBOW;
        break;
      case EXTEND_ELBOW:
        if (m_extendElbow.isFinished())
          m_state = State.SCHEDULE_EXTEND_SHOULDER;
        break;
      case SCHEDULE_EXTEND_SHOULDER:
        m_extendArm.schedule();
        m_state = State.EXTEND_SHOULDER;
        break;
      case EXTEND_SHOULDER:
        if (m_extendArm.isFinished())
          m_state = State.DONE;
        break;
      case DONE:
        m_isFinished = true;
        break;
      default:
        break;
    }
  }

  // Called once the command ends or is interrupted.
  @Override
  public void end(boolean interrupted) {
  }

  // Returns true when the command should end.
  @Override
  public boolean isFinished() {
    return m_isFinished;
  }
}

